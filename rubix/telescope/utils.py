import jax.numpy as jnp
from jaxtyping import Array, Float

def square_spaxel_assignment(coords: Float[Array, " n_stars 3"],
                                        spatial_bin_edges: Float[Array, " n_bins"])-> Float[Array, " n_stars"]:
    """Bin the particle coordinates into a 2D image with the given bin edges for square pixels.

    This function takes the particle coordinates and bins them into a 2D image with the given bin edges.
    The binning is done by digitizing the x and y coordinates of the particles and then calculating the
    flat indices of the 2D image.

    The returned indexes are the pixel assignments of the particles. Indexing starts at 0.

    Parameters
    ----------
    coords : jnp.array (n, 3)
        The particle coordinates.

    spatial_bin_edges : jnp.array
        The bin edges for the spatial bins.

    Returns
    -------
    jnp.array
        The flat pixel assignments of the particles. Indexing starts at 0.

    """

    # Calculate assignment of of x and y coordinates to bins separately
    x_indices = (
        jnp.digitize(coords[:, 0], spatial_bin_edges) - 1
    )  # -1 to start indexing at 0
    y_indices = jnp.digitize(coords[:, 1], spatial_bin_edges) - 1

    number_of_bins = len(spatial_bin_edges) - 1

    # Clip the indices to the valid range
    x_indices = jnp.clip(x_indices, 0, number_of_bins - 1)
    y_indices = jnp.clip(y_indices, 0, number_of_bins - 1)

    # Flatten the 2D indices to 1D indices
    pixel_positions = x_indices + (number_of_bins * y_indices)
    return pixel_positions
