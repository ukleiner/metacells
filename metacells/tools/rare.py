'''
Rare
----
'''

import logging
from typing import Iterable, List, Optional, Tuple

import numpy as np  # type: ignore
import pandas as pd  # type: ignore
import scipy.cluster.hierarchy as sch  # type: ignore
import scipy.spatial.distance as scd  # type: ignore
from anndata import AnnData

import metacells.parameters as pr
import metacells.preprocessing as pp
import metacells.utilities as ut

from .similarity import compute_var_var_similarity

__all__ = [
    'find_rare_gene_modules',
]


LOG = logging.getLogger(__name__)


@ut.timed_call()
@ut.expand_doc()
def find_rare_gene_modules(
    adata: AnnData,
    *,
    of: Optional[str] = None,
    max_gene_cell_fraction: float = pr.rare_max_gene_cell_fraction,
    min_gene_maximum: int = pr.rare_min_gene_maximum,
    similarity_of: Optional[str] = None,
    repeated_similarity: bool = pr.rare_repeated_similarity,
    genes_cluster_method: str = pr.rare_genes_cluster_method,
    min_genes_of_modules: int = pr.rare_min_genes_of_modules,
    min_cells_of_modules: int = pr.rare_min_cells_of_modules,
    target_metacell_size: int = pr.target_metacell_size,
    min_modules_size_factor: float = pr.rare_min_modules_size_factor,
    min_module_correlation: float = pr.rare_min_module_correlation,
    min_cell_module_total: int = pr.rare_min_cell_module_total,
    inplace: bool = True,
    intermediate: bool = True,
) -> Optional[Tuple[ut.PandasFrame, ut.PandasFrame, ut.DenseVector]]:
    '''
    Detect rare genes modules based ``of`` some data (by default, the focus).

    Rare gene modules include genes which are weakly and rarely expressed, yet are highly correlated
    with each other, allowing for robust detection. Global analysis algorithms (such as metacells)
    tend to ignore or at least discount such genes.

    It is therefore useful to explicitly identify, in a pre-processing step, the few cells which
    express such rare gene modules. Once identified, these cells can be exempt from the global
    algorithm, or the global algorithm can be tweaked in some way to pay extra attention to them.

    **Input**

    A :py:func:`metacells.utilities.annotation.setup` annotated ``adata``, where the observations
    are cells and the variables are genes.

    If ``intermediate`` (default: {intermediate}), keep all all the intermediate data (e.g. sums)
    for future reuse. Otherwise, discard it.

    **Returns**

    Observation (Cell) Annotations
        ``cells_rare_gene_module``
            The index of the rare gene module each cell expresses the most, or ``-1`` in the common
            case it does not express any rare genes module.

        ``rare_cells``
            A boolean mask for the (few) cells that express a rare gene module.

    Variable (Gene) Annotations
        ``genes_rare_gene_module``
            The index of the rare gene module each gene belongs to, or ``-1`` in the common case it
            does not belong to any rare genes module.

        ``rare_genes``
            A boolean mask for the genes in any of the rare gene modules.

    Unstructured Annotations
        ``rare_gene_modules``
            An array of rare gene modules, where every entry is the array of the names of the genes
            of the module.

    If ``inplace``, these are written to to the data, and the function returns ``None``. Otherwise
    they are returned as tuple containing two data frames and an array.

    **Computation Parameters**

    1. Pick as candidates all genes that are expressed in more than ``max_gene_cell_fraction``
       (default: {max_gene_cell_fraction}) of the cells, and whose maximal value in a cell is at
       least ``min_gene_maximum`` (default: {min_gene_maximum}).

    2. Compute the similarity between the genes using
       :py:func:`metacells.tools.similarity.compute_var_var_similarity`. Pass it
       ``repeated_similarity`` (default: {repeated_similarity}), which makes sense here since we
       expect the gene expression to be very sparse even for a large number of cells. If
       ``similarity_of`` is specified (default: {similarity_of}), use this data for computing the
       similarity in exactly the way you prefer (e.g., to correlate the log values).

    3. Create a hierarchical clustering of the candidate genes using the ``genes_cluster_method``
       (default: {genes_cluster_method}).

    4. Identify gene modules in the hierarchical clustering which contain at least
       ``min_genes_of_modules`` genes (default: {min_genes_of_modules}), with an average gene-gene
       cross-correlation of at least ``min_module_correlation`` (default:
       {min_module_correlation}).

    5. Associate cells with a gene module if they contain a total value of at least ``min_cell_module_total``
       (default: {min_cell_module_total}) from the module. In the very rare case a cell contains
       this much for multiple gene modules, associate it with the gene module which is most enriched
       (relative to the least enriched cell associated with the gene module). Gene modules with no
       associated cells are discarded. Only accept modules with at least ``min_cells_of_modules``
       (default: {min_cells_of_modules}) and whose total number of UMIs is at least
       ``target_metacell_size`` (default: {target_metacell_size}) * ``min_modules_size_factor``
       (default: {min_modules_size_factor}).
    '''
    level = ut.get_log_level(adata)
    LOG.log(level, 'find_rare_gene_modules...')
    assert min_cells_of_modules > 0
    assert min_genes_of_modules > 0

    with ut.focus_on(ut.get_vo_data, adata, of, intermediate=intermediate):
        cells_count = adata.n_obs
        genes_count = adata.n_vars

        rare_module_of_cells = np.full(cells_count, -1)
        rare_module_of_genes = np.full(genes_count, -1)
        list_of_names_of_genes_of_modules: List[ut.DenseVector] = []

        candidates = \
            _pick_candidates(adata=adata,
                             of=of,
                             max_gene_cell_fraction=max_gene_cell_fraction,
                             min_gene_maximum=min_gene_maximum,
                             min_genes_of_modules=min_genes_of_modules)
        if candidates is None:
            return _results(adata=adata,
                            level=level,
                            rare_module_of_cells=rare_module_of_cells,
                            rare_module_of_genes=rare_module_of_genes,
                            list_of_names_of_genes_of_modules=list_of_names_of_genes_of_modules,
                            inplace=inplace)
        candidate_data, candidate_genes_indices = candidates

        similarities_between_candidate_genes = \
            _genes_similarity(candidate_data=candidate_data,
                              of=similarity_of or of,
                              repeated=repeated_similarity)

        linkage = \
            _cluster_genes(similarities_between_candidate_genes=similarities_between_candidate_genes,
                           genes_cluster_method=genes_cluster_method)

        combined_candidate_indices = \
            _identify_genes(candidate_genes_indices=candidate_genes_indices,
                            similarities_between_candidate_genes=similarities_between_candidate_genes,
                            linkage=linkage,
                            min_module_correlation=min_module_correlation)

        gene_indices_of_modules = \
            _identify_cells(adata=adata,
                            of=of,
                            candidate_data=candidate_data,
                            candidate_genes_indices=candidate_genes_indices,
                            combined_candidate_indices=combined_candidate_indices,
                            rare_module_of_genes=rare_module_of_genes,
                            rare_module_of_cells=rare_module_of_cells,
                            min_genes_of_modules=min_genes_of_modules,
                            min_cell_module_total=min_cell_module_total)
        if len(gene_indices_of_modules) == 0:
            return _results(adata=adata,
                            level=level,
                            rare_module_of_cells=rare_module_of_cells,
                            rare_module_of_genes=rare_module_of_genes,
                            list_of_names_of_genes_of_modules=list_of_names_of_genes_of_modules,
                            inplace=inplace)

        _compress_results(adata=adata,
                          min_cells_of_modules=min_cells_of_modules,
                          target_metacell_size=target_metacell_size,
                          min_modules_size_factor=min_modules_size_factor,
                          gene_indices_of_modules=gene_indices_of_modules,
                          rare_module_of_genes=rare_module_of_genes,
                          rare_module_of_cells=rare_module_of_cells,
                          list_of_names_of_genes_of_modules=list_of_names_of_genes_of_modules)

        return _results(adata=adata,
                        level=level,
                        rare_module_of_cells=rare_module_of_cells,
                        rare_module_of_genes=rare_module_of_genes,
                        list_of_names_of_genes_of_modules=list_of_names_of_genes_of_modules,
                        inplace=inplace)


@ut.timed_call('.pick_candidates')
def _pick_candidates(
    *,
    adata: AnnData,
    of: Optional[str],
    max_gene_cell_fraction: float,
    min_gene_maximum: int,
    min_genes_of_modules: int,
) -> Optional[Tuple[AnnData, ut.DenseVector]]:
    cells_count = adata.n_obs

    LOG.debug('  max_gene_cell_fraction: %s',
              ut.fraction_description(max_gene_cell_fraction))

    nnz_cells_of_genes = pp.get_per_var(adata, ut.nnz_per).proper
    nnz_cell_fraction_of_genes = nnz_cells_of_genes / cells_count
    nnz_cell_fraction_mask_of_genes = \
        nnz_cell_fraction_of_genes <= max_gene_cell_fraction

    LOG.debug('  min_gene_maximum: %s', min_gene_maximum)
    max_umis_of_genes = pp.get_per_var(adata, ut.max_per).proper
    max_umis_mask_of_genes = max_umis_of_genes >= min_gene_maximum

    candidates_mask_of_genes = \
        max_umis_mask_of_genes & nnz_cell_fraction_mask_of_genes

    candidate_genes_indices = np.where(candidates_mask_of_genes)[0]

    candidate_genes_count = candidate_genes_indices.size
    LOG.debug('  candidate_genes_count: %s', candidate_genes_count)
    if candidate_genes_count < min_genes_of_modules:
        return None

    candidate_data = \
        ut.slice(adata, name='candidates', tmp=True,
                 vars=candidate_genes_indices)
    ut.get_vo_data(candidate_data, of or ut.get_focus_name(adata))
    return candidate_data, candidate_genes_indices


@ut.timed_call('.genes_similarity')
def _genes_similarity(
    *,
    candidate_data: AnnData,
    of: Optional[str],
    repeated: bool,
) -> ut.DenseMatrix:
    of = ut.log_of(LOG, candidate_data, of, name='similarity of candidates')
    similarity = \
        compute_var_var_similarity(candidate_data,
                                   of=of,
                                   repeated=repeated,
                                   inplace=False)
    assert similarity is not None
    return ut.to_dense_matrix(similarity)


@ut.timed_call('.cluster_genes')
def _cluster_genes(
    similarities_between_candidate_genes: ut.DenseMatrix,
    genes_cluster_method: str,
) -> List[Tuple[int, int]]:
    with ut.timed_step('scipy.pdist'):
        ut.timed_parameters(size=similarities_between_candidate_genes.shape[0])
        distances = scd.pdist(similarities_between_candidate_genes)

    with ut.timed_step('scipy.linkage'):
        LOG.debug('  genes_cluster_method: %s',
                  genes_cluster_method)
        ut.timed_parameters(size=distances.shape[0],
                            method=genes_cluster_method)
        linkage = sch.linkage(distances, method=genes_cluster_method)

    return linkage


@ut.timed_call('.identify_genes')
def _identify_genes(
    *,
    candidate_genes_indices: ut.DenseVector,
    similarities_between_candidate_genes: ut.DenseMatrix,
    min_module_correlation: float,
    linkage: List[Tuple[int, int]],
) -> Iterable[List[int]]:
    candidate_genes_count = candidate_genes_indices.size
    np.fill_diagonal(similarities_between_candidate_genes, None)
    combined_candidate_indices = \
        {index: [index] for index in range(candidate_genes_count)}

    LOG.debug('  min_module_correlation: %s',
              min_module_correlation)
    for link_index, link_data in enumerate(linkage):
        link_index += candidate_genes_count

        left_index = int(link_data[0])
        right_index = int(link_data[1])

        left_combined_candidates = \
            combined_candidate_indices.get(left_index)
        right_combined_candidates = \
            combined_candidate_indices.get(right_index)
        if not left_combined_candidates or not right_combined_candidates:
            continue

        link_combined_candidates = \
            sorted(left_combined_candidates + right_combined_candidates)
        assert link_combined_candidates
        link_similarities = \
            similarities_between_candidate_genes[link_combined_candidates,  #
                                                 :][:,
                                                    link_combined_candidates]
        average_link_similarity = np.nanmean(link_similarities)
        if average_link_similarity < min_module_correlation:
            continue

        combined_candidate_indices[link_index] = link_combined_candidates
        del combined_candidate_indices[left_index]
        del combined_candidate_indices[right_index]

    return combined_candidate_indices.values()


@ut.timed_call('.identify_cells')
def _identify_cells(
    *,
    adata: AnnData,
    of: Optional[str],
    candidate_data: AnnData,
    candidate_genes_indices: ut.DenseVector,
    combined_candidate_indices: Iterable[List[int]],
    rare_module_of_genes: ut.DenseVector,
    rare_module_of_cells: ut.DenseVector,
    min_genes_of_modules: int,
    min_cell_module_total: int,
) -> List[ut.DenseVector]:
    cells_count = adata.n_obs
    max_strength_of_cells = np.zeros(cells_count)
    gene_indices_of_modules: List[ut.DenseVector] = []
    candidate_umis = \
        ut.get_vo_data(candidate_data, of, layout='column_major')

    LOG.debug('  min_genes_of_modules: %s', min_genes_of_modules)
    LOG.debug('  min_cell_module_total: %s', min_cell_module_total)
    total_umis_of_cells = pp.get_per_obs(adata, ut.sum_per).proper

    for module_candidate_indices in combined_candidate_indices:
        if len(module_candidate_indices) < min_genes_of_modules:
            continue

        total_umis_of_module_of_cells = \
            ut.to_dense_vector(candidate_umis[:,
                                              module_candidate_indices].sum(axis=1))
        assert total_umis_of_module_of_cells.size == cells_count

        min_total_umis_of_module_mask_of_cells = \
            total_umis_of_module_of_cells >= min_cell_module_total
        strong_cell_indices = \
            np.where(min_total_umis_of_module_mask_of_cells)[0]
        if strong_cell_indices.size == 0:
            continue

        total_umis_of_module_of_strong_cells = \
            total_umis_of_module_of_cells[strong_cell_indices]
        total_umis_of_strong_cells = total_umis_of_cells[strong_cell_indices]
        fraction_of_module_of_strong_cells = \
            total_umis_of_module_of_strong_cells / total_umis_of_strong_cells

        min_strong_fraction = fraction_of_module_of_strong_cells.min()
        assert min_strong_fraction > 0
        module_strength_of_strong_cells = \
            fraction_of_module_of_strong_cells / min_strong_fraction

        max_strength_of_strong_cells = \
            max_strength_of_cells[strong_cell_indices]
        stronger_cells_mask = \
            module_strength_of_strong_cells > max_strength_of_strong_cells

        stronger_cell_indices = strong_cell_indices[stronger_cells_mask]
        if stronger_cell_indices.size == 0:
            continue

        max_strength_of_cells[stronger_cell_indices] = \
            max_strength_of_strong_cells[stronger_cells_mask]
        module_index = len(gene_indices_of_modules)
        module_gene_indices = \
            candidate_genes_indices[module_candidate_indices]
        gene_indices_of_modules.append(module_gene_indices)
        rare_module_of_genes[module_gene_indices] = module_index
        rare_module_of_cells[strong_cell_indices] = module_index

    return gene_indices_of_modules


@ut.timed_call('.compress_results')
def _compress_results(
    *,
    adata: AnnData,
    min_cells_of_modules: int,
    target_metacell_size: int,
    min_modules_size_factor: float,
    gene_indices_of_modules: List[ut.DenseVector],
    rare_module_of_genes: ut.DenseVector,
    rare_module_of_cells: ut.DenseVector,
    list_of_names_of_genes_of_modules: List[ut.DenseVector],
) -> None:
    LOG.debug('  target_metacell_size: %s', target_metacell_size)
    LOG.debug('  min_modules_size_factor: %s', min_modules_size_factor)
    min_umis_of_modules = target_metacell_size * min_modules_size_factor
    LOG.debug('  min_umis_of_modules: %s', min_umis_of_modules)
    LOG.debug('  min_cells_of_modules: %s', min_cells_of_modules)
    total_umis_of_cells = pp.get_per_obs(adata, ut.sum_per).proper
    cells_of_modules: List[int] = []
    total_umis_of_modules: List[int] = []
    for raw_module_index, module_gene_indices \
            in enumerate(gene_indices_of_modules):
        module_cell_indices = \
            np.where(rare_module_of_cells == raw_module_index)[0]
        total_umis_of_module = np.sum(total_umis_of_cells[module_cell_indices])

        if module_cell_indices.size < min_cells_of_modules \
                or total_umis_of_module < min_umis_of_modules:
            rare_module_of_cells[module_cell_indices] = -1
            rare_module_of_genes[module_gene_indices] = -1
            continue

        cells_of_modules.append(module_cell_indices.size)
        total_umis_of_modules.append(total_umis_of_module)

        module_index = len(list_of_names_of_genes_of_modules)

        if raw_module_index != module_index:
            rare_module_of_cells[module_cell_indices] = module_index
            rare_module_of_genes[module_gene_indices] = module_index

        names_of_genes_of_module = \
            np.array(adata.var_names[module_gene_indices])
        list_of_names_of_genes_of_modules.append(names_of_genes_of_module)

    if LOG.isEnabledFor(logging.DEBUG):
        for module_index, names_of_genes_of_module \
                in enumerate(list_of_names_of_genes_of_modules):
            LOG.debug('  module: %s / %s cells: %s total UMIs: %d genes: %s',
                      module_index,
                      len(list_of_names_of_genes_of_modules),
                      cells_of_modules[module_index],
                      total_umis_of_modules[module_index],
                      ', '.join(names_of_genes_of_module))


def _results(
    *,
    adata: AnnData,
    level: int,
    rare_module_of_cells: ut.DenseVector,
    rare_module_of_genes: ut.DenseVector,
    list_of_names_of_genes_of_modules: List[ut.DenseVector],
    inplace: bool
) -> Optional[Tuple[pd.DataFrame, pd.DataFrame, ut.DenseVector]]:
    assert np.max(rare_module_of_cells) \
        == len(list_of_names_of_genes_of_modules) - 1
    assert np.max(rare_module_of_genes) \
        == len(list_of_names_of_genes_of_modules) - 1

    array_of_names_of_genes_of_modules = \
        np.array(list_of_names_of_genes_of_modules, dtype='object')

    if inplace:
        ut.set_m_data(adata, 'rare_gene_modules',
                      array_of_names_of_genes_of_modules)
        ut.set_v_data(adata, 'genes_rare_gene_module', rare_module_of_genes,
                      log_value=ut.groups_description)
        ut.set_v_data(adata, 'rare_gene', rare_module_of_genes >= 0)
        ut.set_o_data(adata, 'cells_rare_gene_module', rare_module_of_cells,
                      log_value=ut.groups_description)
        ut.set_o_data(adata, 'rare_cell', rare_module_of_cells >= 0)
        return None

    obs_metrics = pd.DataFrame(index=adata.obs_names)
    var_metrics = pd.DataFrame(index=adata.var_names)

    obs_metrics['cells_rare_gene_module'] = rare_module_of_cells
    obs_metrics['rare_cell'] = rare_module_of_cells >= 0
    var_metrics['genes_rare_gene_module'] = rare_module_of_genes
    var_metrics['rare_gene'] = rare_module_of_genes >= 0

    if LOG.isEnabledFor(level):
        LOG.log(level, '  rare_gene_modules: %s', rare_module_of_genes.size)
        ut.log_mask(LOG, level, 'rare_cells', rare_module_of_cells >= 0)
        ut.log_mask(LOG, level, 'rare_genes', rare_module_of_genes >= 0)

    return obs_metrics, var_metrics, array_of_names_of_genes_of_modules