import jax.numpy as jnp
from jaxtyping import Float, Array
from rubix.telescope.utils import (
    calculate_spatial_bin_edges,
    square_spaxel_assignment,
    mask_particles_outside_aperture,
)
from rubix.telescope.base import BaseTelescope
from rubix.telescope.factory import TelescopeFactory
from .cosmology import get_cosmology
from .data import RubixData
from typing import Callable


def get_telescope(config: dict) -> BaseTelescope:
    """Get the telescope object based on the configuration."""
    # TODO: this currently only loads telescope that are supported.
    # add support for custom telescopes
    factory = TelescopeFactory()
    telescope = factory.create_telescope(config["telescope"]["name"])
    return telescope


def get_spatial_bin_edges(config: dict) -> Float[Array, " n_bins"]:
    """Get the spatial bin edges based on the configuration."""
    telescope = get_telescope(config)
    galaxy_dist_z = config["galaxy"]["dist_z"]
    cosmology = get_cosmology(config)
    # Calculate the spatial bin edges
    # TODO: check if we need the spatial bin size somewhere? For now we dont use it
    spatial_bin_edges, spatial_bin_size = calculate_spatial_bin_edges(
        fov=telescope.fov,
        spatial_bins=telescope.sbin,
        dist_z=galaxy_dist_z,
        cosmology=cosmology,
    )

    return spatial_bin_edges


def get_spaxel_assignment(config: dict) -> Callable:
    """Get the spaxel assignment function based on the configuration."""
    telescope = get_telescope(config)
    if telescope.pixel_type not in ["square"]:
        raise ValueError(f"Pixel type {telescope.pixel_type} not supported")
    spatial_bin_edges = get_spatial_bin_edges(config)

    def spaxel_assignment(rubixdata: RubixData) -> RubixData:
        def assign_particle(particle):
            if particle.coords is not None:
                pixel_assignment = square_spaxel_assignment(
                    particle.coords, spatial_bin_edges
                )
                particle.pixel_assignment = pixel_assignment
                particle.spatial_bin_edges = spatial_bin_edges
            return particle

        rubixdata.stars = assign_particle(rubixdata.stars)
        rubixdata.gas = assign_particle(rubixdata.gas)

        return rubixdata

    return spaxel_assignment


def get_filter_particles(config: dict):
    """Get the function to filter particles outside the aperture."""
    spatial_bin_edges = get_spatial_bin_edges(config)

    def filter_particles(rubixdata: RubixData) -> RubixData:
        if "stars" in config["data"]["args"]["particle_type"]:
            # if rubixdata.stars.coords is not None:
            mask = mask_particles_outside_aperture(
                rubixdata.stars.coords, spatial_bin_edges
            )

            attributes = [
                attr
                for attr in dir(rubixdata.stars)
                if not attr.startswith("__")
                and not callable(getattr(rubixdata.stars, attr))
                and attr not in ("coords", "velocity")
            ]
            for attr in attributes:
                current_attr_value = getattr(rubixdata.stars, attr)
                # Apply mask only if current_attr_value is an ndarray
                if isinstance(current_attr_value, jnp.ndarray):
                    setattr(
                        rubixdata.stars, attr, jnp.where(mask, current_attr_value, 0)
                    )
            mask_jax = jnp.array(mask)
            setattr(rubixdata.stars, "mask", mask_jax)
            # rubixdata.stars.mask = mask

        if "gas" in config["data"]["args"]["particle_type"]:
            mask = mask_particles_outside_aperture(
                rubixdata.gas.coords, spatial_bin_edges
            )
            attributes = [
                attr
                for attr in dir(rubixdata.gas)
                if not attr.startswith("__")
                and not callable(getattr(rubixdata.gas, attr))
                and attr not in ("coords", "velocity")
            ]
            for attr in attributes:
                current_attr_value = getattr(rubixdata.gas, attr)
                if isinstance(current_attr_value, jnp.ndarray):
                    setattr(rubixdata.gas, attr, jnp.where(mask, current_attr_value, 0))
                # rubixdata.gas.__setattr__(attr, jnp.where(mask, rubixdata.gas.__getattribute__(attr), 0))
            mask_jax = jnp.array(mask)
            setattr(rubixdata.gas, "mask", mask_jax)
            # rubixdata.gas.mask = mask

        return rubixdata

    return filter_particles


# def get_split_data(config: dict, n_particles) -> Callable:
#     telescope = get_telescope(config)
#     n_pixels = telescope.sbin**2
#
#     def split_data(input_data: dict) -> dict:
#         # Split the data into two parts
#
#         masses, metallicity, ages = restructure_data(
#             input_data["mass"],
#             input_data["metallicity"],
#             input_data["age"],
#             input_data["pixel_assignment"],
#             n_pixels,
#             # n_particles,
#         )
#
#         # Reshape the data to match the number of GPUs
#
#         input_data["masses"] = masses
#         input_data["metallicity"] = metallicity
#         input_data["age"] = ages
#
#         return input_data
#
#     return split_data
