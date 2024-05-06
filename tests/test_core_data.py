import pytest
from unittest.mock import patch, MagicMock

# Assume the module name is rubix_conversion.py where the functions are located
from rubix.core.data import convert_to_rubix, prepare_input

# Mock configuration for tests
config_dict = {
    "data": {
        "name": "IllustrisAPI",
        "args": {"api_key": "your_api_key"},
        "load_galaxy_args": {"snapshot": "latest"},
    },
    "output_path": "/path/to/output",
    "logger": {"level": "DEBUG"},
}

config_path = "path/to/config.yaml"


# Test convert_to_rubix function
@patch("rubix.core.data.read_yaml")
@patch("rubix.core.data.get_logger")
@patch("rubix.core.data.get_input_handler")
@patch("rubix.core.data.IllustrisAPI")
def test_convert_to_rubix(
    mock_illustris_api, mock_input_handler, mock_logger, mock_read_yaml
):
    mock_read_yaml.return_value = config_dict
    mock_logger.return_value = MagicMock()
    mock_input_handler.return_value = MagicMock()
    mock_input_handler.return_value.to_rubix.return_value = None
    mock_illustris_api.return_value = MagicMock()
    mock_illustris_api.return_value.load_galaxy.return_value = None

    output_path = convert_to_rubix(config_path)
    assert output_path == config_dict["output_path"]
    mock_read_yaml.assert_called_once_with(config_path)
    mock_logger.assert_called_once()
    mock_input_handler.assert_called_once()
    mock_illustris_api.assert_called_once()


# Test prepare_input function
@patch("rubix.core.data.os.path.join")
@patch("rubix.core.data.load_galaxy_data")
@patch("rubix.core.data.center_particles")
def test_prepare_input(mock_center_particles, mock_load_galaxy_data, mock_path_join):
    mock_path_join.return_value = "/path/to/output/rubix_galaxy.h5"
    mock_load_galaxy_data.return_value = {
        "particle_data": {
            "stars": {
                "coords": [[1, 2, 3]],
                "velocities": [[4, 5, 6]],
                "metallicity": [0.1],
                "mass": [1000],
                "age": [4.5],
            },
            "subhalo_center": [0, 0, 0],
        }
    }
    mock_center_particles.return_value = ([[1, 2, 3]], [[4, 5, 6]])

    coords, velocities, metallicity, mass, age = prepare_input(config_dict)

    assert coords == [[1, 2, 3]]
    assert velocities == [[4, 5, 6]]
    assert metallicity == [0.1]
    assert mass == [1000]
    assert age == [4.5]

    mock_path_join.assert_called_once_with(
        config_dict["output_path"], "rubix_galaxy.h5"
    )
    mock_load_galaxy_data.assert_called_once()
    mock_center_particles.assert_called_once()