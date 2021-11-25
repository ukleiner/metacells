"""
Project
-------
"""

from typing import Tuple
from typing import Union

import numpy as np
from anndata import AnnData  # type: ignore
from scipy import sparse  # type: ignore

import metacells.parameters as pr
import metacells.utilities as ut

__all__ = [
    "project_query_onto_atlas",
]


@ut.logged()
@ut.timed_call()
@ut.expand_doc()
def project_query_onto_atlas(
    *,
    adata: AnnData,
    qdata: AnnData,
    what: Union[str, ut.Matrix] = "__x__",
    project_fold_normalization: float = pr.project_fold_normalization,
    project_candidates_count: int = pr.project_candidates_count,
    project_min_significant_gene_value: float = pr.project_min_significant_gene_value,
    project_min_usage_weight: float = pr.project_min_usage_weight,
    project_min_consistency_weight: float = pr.project_min_consistency_weight,
    project_max_consistency_fold: float = pr.project_max_consistency_fold,
    project_max_inconsistent_genes: int = pr.project_max_inconsistent_genes,
    project_max_projection_fold: float = pr.project_max_projection_fold,
) -> ut.CompressedMatrix:
    """
    Project query metacells onto atlas metacells.

    **Input**

    Annotated query ``qdata`` and atlas ``adata``, where the observations are cells and the variables are genes, where
    ``what`` is a per-variable-per-observation matrix or the name of a per-variable-per-observation annotation
    containing such a matrix.

    **Returns**

    A matrix whose rows are query metacells and columns are atlas metacells, where each entry is the weight of the atlas
    metacell in the projection of the query metacells. The sum of weights in each row (that is, for a single query
    metacell) is 1. The weighted sum of the atlas metacells using these weights is the "projected" image of the query
    metacell onto the atlas.

    In addition, sets the following annotations in ``qdata``:

    Observation (Cell) Annotations
        ``charted``
            A boolean mask indicating whether the query metacell is meaningfully projected onto the atlas. If ``False``
            the metacells is said to be "uncharted", which may indicate the query contains cell states that do not
            appear in the atlas.

    Observation-Variable (Cell-Gene) Annotations
        ``projected``
            A matrix of UMIs where the sum of UMIs for each query metacell is the same as the sum of ``what`` UMIs,
            describing the "projected" image of the query metacell onto the atlas.


    **Computation Parameters**

    0. All fold computations (log2 of the ratio between gene expressions as a fraction of the total UMIs) use the
       ``project_fold_normalization`` (default: {project_fold_normalization}).

    For each query metacell:

    1. Find the ``project_candidates_count`` (default: {project_candidates_count}) atlas metacells with the lowest
       maximal gene fold factor relative to the query metacell.

    2. Compute the non-negative weights (with a sum of 1) of the atlas candidates that give the best projection of the
       query metacells onto the atlas. Since the algorithm for computing these weights rarely produces an exact 0
       weight, reduce all weights less than the ``project_min_usage_weight`` (default: {project_min_usage_weight}) to
       zero.

    3. Consider genes whose total UMIs in the query metacell and the projected image (scaled to the same total number of
       UMIs) is at least ``project_min_significant_gene_value`` (default: {project_min_significant_gene_value}).

    4. For each such gene,. consider the fold factor between the query metacell and its projection. If this is above
       ``project_max_projection_fold`` (default: {project_max_projection_fold}), declare the query metacell as
       uncharted.

    5. For each such gene consider the fold factor between its maximal and minimal expression in the atlas candidates
       whose weight is at least ``project_min_consistency_weight`` (default: {project_min_consistency_weight}). If there
       are more than ``project_max_inconsistent_genes`` (default: {project_max_inconsistent_genes}) genes whose fold
       factor is above ``project_max_consistency_fold`` (default: {project_max_consistency_fold}), declare the query
       metacell as uncharted.
    """
    assert project_fold_normalization > 0
    assert project_candidates_count > 0
    assert project_min_significant_gene_value >= 0
    assert project_min_usage_weight >= 0
    assert project_min_consistency_weight >= 0
    assert project_max_consistency_fold >= 0
    assert project_max_inconsistent_genes >= 0
    assert np.all(adata.var_names == qdata.var_names)

    atlas_umis = ut.get_vo_proper(adata, what, layout="row_major")
    query_umis = ut.get_vo_proper(qdata, what, layout="row_major")
    atlas_total_umis = ut.sum_per(atlas_umis, per="row")

    atlas_fractions = ut.to_numpy_matrix(ut.fraction_by(atlas_umis, by="row"))
    query_fractions = ut.to_numpy_matrix(ut.fraction_by(query_umis, by="row"))

    atlas_fractions += project_fold_normalization
    query_fractions += project_fold_normalization

    atlas_log_fractions = np.log2(atlas_fractions)
    query_log_fractions = np.log2(query_fractions)

    atlas_fractions -= project_fold_normalization
    query_fractions -= project_fold_normalization

    @ut.timed_call("project_single_metacell")
    def _project_single(query_metacell_index: int) -> Tuple[bool, ut.NumpyVector, ut.NumpyVector, float]:
        return _project_single_metacell(
            atlas_umis=atlas_umis,
            atlas_total_umis=atlas_total_umis,
            query_umis=query_umis,
            atlas_fractions=atlas_fractions,
            query_fractions=query_fractions,
            atlas_log_fractions=atlas_log_fractions,
            query_log_fractions=query_log_fractions,
            project_fold_normalization=project_fold_normalization,
            project_candidates_count=project_candidates_count,
            project_min_significant_gene_value=project_min_significant_gene_value,
            project_min_usage_weight=project_min_usage_weight,
            project_min_consistency_weight=project_min_consistency_weight,
            project_max_consistency_fold=project_max_consistency_fold,
            project_max_inconsistent_genes=project_max_inconsistent_genes,
            project_max_projection_fold=project_max_projection_fold,
            query_metacell_index=query_metacell_index,
        )

    results = list(ut.parallel_map(_project_single, qdata.n_obs))

    charted = np.array([result[0] for result in results])
    indices = np.concatenate([result[1] for result in results], dtype="int32")
    data = np.concatenate([result[2] for result in results], dtype="float32")
    projected_total_umis = np.array([result[3] for result in results], dtype="float32")

    ut.set_o_data(qdata, "charted", charted)

    atlas_used_sizes = [len(result[1]) for result in results]
    atlas_used_sizes.insert(0, 0)
    indptr = np.cumsum(np.array(atlas_used_sizes))

    sparse_weights = sparse.csr_matrix((data, indices, indptr), shape=(qdata.n_obs, adata.n_obs))

    dense_weights = ut.to_numpy_matrix(sparse_weights)
    projected = dense_weights @ atlas_fractions
    assert projected.shape == query_fractions.shape
    projected *= projected_total_umis[:, np.newaxis]
    ut.set_vo_data(qdata, "projected", projected)

    return sparse_weights


@ut.logged()
def _project_single_metacell(  # pylint: disable=too-many-statements
    *,
    atlas_umis: ut.Matrix,
    atlas_total_umis: ut.NumpyVector,
    query_umis: ut.Matrix,
    atlas_fractions: ut.NumpyMatrix,
    query_fractions: ut.NumpyMatrix,
    atlas_log_fractions: ut.NumpyMatrix,
    query_log_fractions: ut.NumpyMatrix,
    project_fold_normalization: float,
    project_candidates_count: int,
    project_min_significant_gene_value: float,
    project_min_usage_weight: float,
    project_min_consistency_weight: float,
    project_max_consistency_fold: float,
    project_max_inconsistent_genes: int,
    project_max_projection_fold: float,
    query_metacell_index: int,
) -> Tuple[bool, ut.NumpyVector, ut.NumpyVector, float]:
    query_metacell_umis = query_umis[query_metacell_index, :]
    ut.log_calc("query_total_umis", np.sum(query_metacell_umis))
    query_metacell_fractions = query_fractions[query_metacell_index, :]
    query_metacell_log_fractions = query_log_fractions[query_metacell_index, :]

    if project_candidates_count < atlas_log_fractions.shape[0]:
        query_atlas_fold_factors = atlas_log_fractions - query_metacell_log_fractions[np.newaxis, :]
        query_atlas_fold_factors = np.abs(query_atlas_fold_factors, out=query_atlas_fold_factors)
        total_umis = atlas_umis + query_metacell_umis[np.newaxis, :]
        insignificant_folds_mask = total_umis < project_min_significant_gene_value
        ut.log_calc("significant_folds_mask", ~insignificant_folds_mask)
        query_atlas_fold_factors[insignificant_folds_mask] = 0.0
        query_atlas_max_fold_factors = ut.max_per(query_atlas_fold_factors, per="row")
        atlas_candidate_indices = np.argpartition(query_atlas_max_fold_factors, project_candidates_count)[
            0:project_candidates_count
        ]
        atlas_candidate_indices.sort()
        atlas_candidate_fractions = atlas_fractions[atlas_candidate_indices, :]
    else:
        atlas_candidate_indices = np.arange(atlas_log_fractions.shape[0])
        atlas_candidate_fractions = atlas_fractions

    represent_result = ut.represent(query_metacell_fractions, atlas_candidate_fractions)
    assert represent_result is not None
    atlas_candidate_weights = represent_result[1]
    atlas_candidate_weights[atlas_candidate_weights < project_min_usage_weight] = 0
    atlas_candidate_weights[atlas_candidate_weights < project_min_usage_weight] /= np.sum(atlas_candidate_weights)

    atlas_candidate_used_mask = atlas_candidate_weights > 0
    atlas_used_weights = atlas_candidate_weights[atlas_candidate_used_mask]
    atlas_used_indices = atlas_candidate_indices[atlas_candidate_used_mask]
    atlas_used_umis = atlas_umis[atlas_used_indices, :]
    atlas_used_fractions = atlas_fractions[atlas_used_indices, :]
    atlas_used_log_fractions = atlas_log_fractions[atlas_used_indices, :]

    projected_fractions = atlas_used_weights @ atlas_used_fractions
    projected_log_fractions = np.log2(projected_fractions + project_fold_normalization)

    projected_total_umis = float(atlas_used_weights @ atlas_total_umis[atlas_used_indices])
    projected_umis = projected_fractions * projected_total_umis
    total_gene_umis = query_metacell_umis + projected_umis
    significant_genes_mask = total_gene_umis >= project_min_significant_gene_value
    ut.log_calc("significant_genes_mask", significant_genes_mask)

    query_projected_fold_factors = (
        projected_log_fractions[significant_genes_mask] - query_metacell_log_fractions[significant_genes_mask]
    )
    query_projected_fold_factors = np.abs(query_projected_fold_factors, out=query_projected_fold_factors)
    query_max_projected_fold_factor = np.max(query_projected_fold_factors)
    ut.log_calc("query_max_projected_fold_factor", query_max_projected_fold_factor)
    charted = query_max_projected_fold_factor <= project_max_projection_fold

    if charted:
        atlas_consistency_used_mask = atlas_used_weights >= project_min_consistency_weight
        atlas_consistency_min_log_fractions = np.full(len(query_metacell_umis), 1e9, dtype="float32")
        atlas_consistency_max_log_fractions = np.full(len(query_metacell_umis), -1e9, dtype="float32")
        for position in np.where(atlas_consistency_used_mask)[0]:
            atlas_metacell_umis = atlas_used_umis[position, :]
            atlas_metacell_log_fractions = atlas_used_log_fractions[position, :]
            total_umis = query_metacell_umis + atlas_metacell_umis
            significant_folds_mask = total_umis >= project_min_significant_gene_value
            atlas_consistency_min_log_fractions[significant_folds_mask] = np.minimum(
                atlas_consistency_min_log_fractions[significant_folds_mask],
                atlas_metacell_log_fractions[significant_folds_mask],
            )
            atlas_consistency_max_log_fractions[significant_folds_mask] = np.maximum(
                atlas_consistency_max_log_fractions[significant_folds_mask],
                atlas_metacell_log_fractions[significant_folds_mask],
            )
        atlas_consistency_min_log_fractions[atlas_consistency_min_log_fractions == 1e9] = 0
        atlas_consistency_max_log_fractions[atlas_consistency_max_log_fractions == -1e9] = 0
        atlas_consistency_fold_factors = atlas_consistency_max_log_fractions - atlas_consistency_min_log_fractions
        atlas_inconsistent_genes_mask = atlas_consistency_fold_factors > project_max_consistency_fold
        atlas_inconsistent_genes_count = np.sum(atlas_inconsistent_genes_mask)
        ut.log_calc("inconsistent genes", atlas_inconsistent_genes_count)
        charted = atlas_inconsistent_genes_count <= project_max_inconsistent_genes

    atlas_used_indices = atlas_used_indices.astype("int32")
    atlas_used_weights = atlas_used_weights.astype("float32")
    ut.log_return("charted", charted)
    ut.log_return("atlas_used_indices", atlas_used_indices)
    ut.log_return("atlas_used_weights", atlas_used_weights)
    ut.log_return("projected_total_umis", projected_total_umis)
    return (charted, atlas_used_indices, atlas_used_weights, projected_total_umis)