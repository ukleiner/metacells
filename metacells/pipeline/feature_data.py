'''
Feature Data
------------
'''

import logging
from re import Pattern
from typing import Collection, Optional, Union

from anndata import AnnData

import metacells.preprocessing as pp
import metacells.tools as tl
import metacells.utilities as ut

__all__ = [
    'extract_feature_data',
]


LOG = logging.getLogger(__name__)


@ut.timed_call()
@ut.expand_doc()
def extract_feature_data(
    adata: AnnData,
    of: Optional[str] = None,
    *,
    name: Optional[str] = 'FEATURE',
    tmp: bool = True,
    downsample_cell_quantile: float = 0.05,
    random_seed: int = 0,
    min_relative_variance_of_genes: float = 0.1,
    min_fraction_of_genes: float = 1e-5,
    forbidden_gene_names: Optional[Collection[str]] = None,
    forbidden_gene_patterns: Optional[Collection[Union[str, Pattern]]] = None,
    intermediate: bool = True,
) -> Optional[AnnData]:
    '''
    Extract a "feature" subset of the ``adata`` to compute metacells for.

    When computing metacells (or clustering cells in general), it makes sense to use a subset of the
    genes for computing cell-cell similarity, for both technical (e.g., too low an expression level)
    and biological (e.g., ignoring bookkeeping and cell cycle genes) reasons. The steps provided
    here are expected to be generically useful, but as always specific data sets may require custom
    feature selection steps on a case-by-case basis.

    **Input**

    A presumably "clean" :py:func:`metacells.utilities.annotation.setup` annotated ``adata``, where
    the observations are cells and the variables are genes.

    All the computations will use the ``of`` data (by default, the focus).

    **Returns**

    Annotated sliced data containing the "feature" subset of the original data. The focus of the
    data will be the (slice) ``of`` the (downsampled) input data. By default, the ``name`` of this
    data is ``FEATURE``.

    If ``intermediate`` (default: {intermediate}), keep all all the intermediate data (e.g. sums)
    for future reuse. Otherwise, discard it.

    **Computation Parameters**

    1. Invoke :py:func:`metacells.tools.downsample_cells.downsample_cells` to downsample the cells
       to the same total number of UMIs, using the ``downsample_cell_quantile`` (default:
       {downsample_cell_quantile}) and the ``random_seed`` (default: {random_seed}).

    2. Invoke :py:func:`metacells.tools.high_genes.find_high_relative_variance_genes` to select
       high-variance feature genes (based on the downsampled data), using
       ``min_relative_variance_of_genes``.

    2. Invoke :py:func:`metacells.tools.high_genes.find_high_fraction_genes` to select
       high-expression feature genes (based on the downsampled data), using
       ``min_fraction_of_genes``.

    3. Invoke :py:func:`metacells.tools.named_genes.find_named_genes` to forbid genes from being
       used as feature genes, based on their name. using the ``forbidden_gene_names`` (default:
       {forbidden_gene_names}) and ``forbidden_gene_patterns`` (default: {forbidden_gene_patterns}).
       This is stored in an intermediate per-variable (gene) ``forbidden_genes`` boolean mask.

    5. Invoke :py:func:`metacells.preprocessing.filter_data.filter_data` to slice just the selected
       "feature" genes using the ``name`` (default: {name}) and ``tmp`` (default: {tmp}).
    '''
    ut.log_pipeline_step(LOG, adata, 'extract_feature_data')

    with ut.focus_on(ut.get_vo_data, adata, of, intermediate=intermediate):
        tl.downsample_cells(adata,
                            downsample_cell_quantile=downsample_cell_quantile,
                            random_seed=random_seed,
                            infocus=True)

        tl.find_high_relative_variance_genes(adata,
                                             min_relative_variance_of_genes=min_relative_variance_of_genes)

        tl.find_high_fraction_genes(adata,
                                    min_fraction_of_genes=min_fraction_of_genes)

        if forbidden_gene_names is not None \
                or forbidden_gene_patterns is not None:
            tl.find_named_genes(adata,
                                to='forbidden_genes',
                                names=forbidden_gene_names,
                                patterns=forbidden_gene_patterns)

        fdata = pp.filter_data(adata, name=name, tmp=tmp,
                               masks=['high_fraction_genes',
                                      'high_relative_variance_genes',
                                      '~forbidden_genes'])

    if fdata is not None:
        ut.get_vo_data(fdata, ut.get_focus_name(adata), infocus=True)

    return fdata
