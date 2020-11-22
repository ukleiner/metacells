'''
Project
-------
'''

import logging
from typing import Any, Callable, Optional

import numpy as np  # type: ignore
from anndata import AnnData

import metacells.utilities as ut

__all__ = [
    'project_group_to_obs',
    'project_obs_to_obs',
    'project_obs_to_group',
]


LOG = logging.getLogger(__name__)


@ut.timed_call()
def project_group_to_obs(
    *,
    adata: AnnData,
    gdata: AnnData,
    group: str,
    property_name: str,
    to_property_name: Optional[str] = None,
    default: Any = None,
) -> None:
    '''
    Project the value of a property from per-group data to per-observation data.

    The input annotated ``gdata`` is expected to contain a per-observation (group)
    annotation named ``property_name``. The input annotated ``adata`` is expected
    to contain a per-observation annotation named ``group`` which identifies the
    group each observation (cell) belongs to.

    This will generate a new per-observation (cell) annotation in ``adata``, named
    ``to_property_name`` (by default, the same as ``property_name``), containing the value of the
    property for the group it belongs to. If the ``group`` annotation contains a negative number
    instead of a valid group index, the ``default`` value is used.
    '''
    ut.log_operation(LOG, adata, 'project_group_to_obs')

    if to_property_name is None:
        to_property_name = property_name

    group_of_obs = ut.to_dense_vector(ut.get_o_data(adata, group))
    property_of_group = ut.get_o_data(gdata, property_name)
    property_of_obs = np.array([default if group < 0 else property_of_group[group]
                                for group in group_of_obs])
    ut.set_o_data(adata, to_property_name, property_of_obs)


@ut.timed_call()
def project_obs_to_obs(
    *,
    adata: AnnData,
    bdata: AnnData,
    property_name: str,
    to_property_name: Optional[str] = None,
    default: Any = None,
) -> None:
    '''
    Project the value of a property from one annotated data to another.

    The observation names are expected to be compatible between ``adata`` and ``bdata``.
    The annotated ``adata`` is expected to contain a per-observation (cell) annotation
    named ``property_name``.

    This will generate a new per-observation (cell) annotation in ``bdata``, named
    ``to_property_name`` (by default, the same as ``property_name``), containing the value of the
    observation with the same name in ``adata``. If no such observation exists, the ``default``
    value is used.
    '''
    ut.log_operation(LOG, adata, 'project_obs_to_obs')

    if to_property_name is None:
        to_property_name = property_name

    property_of_from = ut.get_o_data(adata, property_name)
    property_of_name = {name: property_of_from[index]
                        for index, name in enumerate(adata.obs_names)}
    property_of_to = np.array([property_of_name.get(name, default)
                               for name in bdata.obs_names])
    ut.set_o_data(bdata, to_property_name, property_of_to)


@ut.timed_call()
def project_obs_to_group(
    *,
    adata: AnnData,
    gdata: AnnData,
    group: str,
    property_name: str,
    to_property_name: Optional[str] = None,
    method: Callable[[ut.Vector], Any] = ut.most_frequent,
) -> None:
    '''
    Project the value of a property from per-observation data to per-group data.

    The input annotated ``adata`` is expected to contain a per-observation (group) annotation named
    ``property_name`` and also a per-observation annotation named ``group`` which identifies the
    group each observation (cell) belongs to, which must be an integer.

    This will generate a new per-observation (cell) annotation in ``gdata``, named
    ``to_property_name`` (by default, the same as ``property_name``), containing the aggregated
    value of the property of all the observations (cells) that belong to the group.

    The aggregation method (by default, :py:func:`metacells.utilities.computation.most_frequent`) is
    any function taking an array of values and returning a single value.
    '''
    ut.log_operation(LOG, adata, 'project_obs_to_group')

    if to_property_name is None:
        to_property_name = property_name

    property_of_obs = ut.get_o_data(adata, property_name)
    group_of_obs = ut.get_o_data(adata, group)
    property_of_group = \
        np.array([method(property_of_obs[group_of_obs == group])
                  for group in range(gdata.n_obs)])
    ut.set_o_data(gdata, to_property_name, property_of_group)