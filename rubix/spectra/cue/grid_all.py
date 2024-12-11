import jax.numpy as jnp
import numpy as np
from jax import vmap
import jax
from cue.line import predict as line_predict
from cue.continuum import predict as cont_predict

# from cue.line import predict as line_predict
# from cue.continuum import predict as cont_predict
from rubix.core.telescope import get_telescope
from rubix.spectra.ifu import convert_luminoisty_to_flux_gas
from rubix import config as rubix_config
from rubix.logger import get_logger
from rubix.cosmology.base import BaseCosmology
from jax.experimental import jax2tf
import tensorflow as tf


class CueGasLookup:
    def __init__(self, preprocessed_data):
        self.config = preprocessed_data["config"]
        self.telescope = preprocessed_data["telescope"]
        self.observation_lum_dist = preprocessed_data["observation_lum_dist"]
        self.factor = preprocessed_data["factor"]

    def illustris_gas_temp(self, rubixdata):
        """
        Calculation the tempeature for each gas cell in the galaxy.

        Returns the temperature of the gas in the galaxy according to the Illustris simulation.
        See https://www.tng-project.org/data/docs/faq/ under Section General point 6 for more details.

        Parameters:
        rubixdata (RubixData): The RubixData object containing the gas data.

        Returns:
        rubixdata (RubixData): The RubixData object with the gas temperature added to rubixdata.gas.temperature.
        """
        logger = get_logger(self.config.get("logger", None))
        logger.info("Calculating gas temperature")

        # Convert internal energy
        internal_energy_u = rubixdata.gas.internal_energy
        # Electron abundance
        electron_abundance = rubixdata.gas.electron_abundance
        # Constants
        x_h = 0.76  # hydrogen mass fraction
        m_p = 1.6726219e-24  # proton mass in CGS units (g)
        gamma = 5 / 3  # adiabatic index
        k_b = 1.38064852e-16  # Boltzmann constant in CGS units (erg/K), https://www.physics.rutgers.edu/~abrooks/342/constants.html

        # Mean molecular weight
        mean_molecular_weight = 4.0 / (1 + 3 * x_h + 4 * x_h * electron_abundance) * m_p

        # Temperature calculation
        temperature = (gamma - 1) * internal_energy_u / k_b * mean_molecular_weight

        # Assign temperature to rubixdata
        rubixdata.gas.temperature = temperature

        return rubixdata

    def get_theta(self, rubixdata):
        """
        Returns the theta parameters for the Cue model (Li et al. 2024) for the shape of the ionizing spectrum and the ionizing gas properties.
        The theta parameters are calculated for each gas cell with the Illustris data.
        Be aware that we are using default values for the theta parameters for the ionizing spectrum shape from the CUE github repository.
        https://github.com/yi-jia-li/cue

        Parameters:
        rubixdata (RubixData): The RubixData object containing the gas data.

        Returns:
        jnp.ndarray: The theta parameters that are the input for the Cue model.

        Cue states in their code in line.py
        Nebular Line Emission Prediction
        :param theta: nebular parameters of n samples, (n, 12) matrix
        :param gammas, log_L_ratios, log_QH, n_H, log_OH_ratio, log_NO_ratio, log_CO_ratio: 12 input parameters
        """
        logger = get_logger(self.config.get("logger", None))
        logger.warning(
            "Using default theta parameters for the Cue model (Li et al. 2024) for the shape of the ionizing spectrum. Ionizing gas properties are calculated for each gas cell with the Illustris data."
        )
        alpha_HeII = jnp.full(len(rubixdata.gas.mass), 21.5)
        alpha_OII = jnp.full(len(rubixdata.gas.mass), 14.85)
        alpha_HeI = jnp.full(len(rubixdata.gas.mass), 6.45)
        alpha_HI = jnp.full(len(rubixdata.gas.mass), 3.15)
        log_OII_HeII = jnp.full(len(rubixdata.gas.mass), 4.55)
        log_HeI_OII = jnp.full(len(rubixdata.gas.mass), 0.7)
        log_HI_HeI = jnp.full(len(rubixdata.gas.mass), 0.85)
        # log_QH = rubixdata.gas.electron_abundance
        n_H = rubixdata.gas.density
        # n_H = jnp.full(len(rubixdata.gas.mass), 10**2.5)
        OH_ratio = rubixdata.gas.metals[:, 4] / rubixdata.gas.metals[:, 0]
        NO_ratio = rubixdata.gas.metals[:, 3] / rubixdata.gas.metals[:, 4]
        CO_ratio = rubixdata.gas.metals[:, 2] / rubixdata.gas.metals[:, 4]

        log_oh_sol = -3.07
        log_co_sol = -0.37
        log_no_sol = -0.88

        oh_factor = 16 / 1
        co_factor = 12 / 16
        no_factor = 14 / 16

        final_log_oh = jnp.log10(OH_ratio * oh_factor) / log_oh_sol
        final_log_co = jnp.log10(CO_ratio * co_factor) / 10**log_co_sol
        final_log_no = jnp.log10(NO_ratio * no_factor) / 10**log_no_sol
        log_QH = jnp.full(len(rubixdata.gas.mass), 49.58)

        log_OH_ratio = jnp.full(len(rubixdata.gas.mass), -0.85)
        log_NO_ratio = jnp.full(len(rubixdata.gas.mass), -0.134)
        log_CO_ratio = jnp.full(len(rubixdata.gas.mass), -0.134)

        theta = [
            alpha_HeII,
            alpha_OII,
            alpha_HeI,
            alpha_HI,
            log_OII_HeII,
            log_HeI_OII,
            log_HI_HeI,
            log_QH,
            n_H,
            # final_log_oh,
            # final_log_no,
            # final_log_co,
            log_OH_ratio,
            log_NO_ratio,
            log_CO_ratio,
        ]
        theta = jnp.transpose(jnp.array(theta))
        logger.debug(f"theta: {theta.shape}")
        logger.debug(f"theta: {theta}")
        return theta

    def dispersionfactor(self, rubixdata):
        """
        Calculates the thermal broadening of the emission lines.
        We follow the formular of https://pyastronomy.readthedocs.io/en/latest/pyaslDoc/aslDoc/thermalBroad.html
        To get the dispersion, this factor has to be multiplied by the wavelength of the emission line.
        Expected to be around 1 Angstom for temperatures of 10^4 K.

        Parameters:
        rubixdata (RubixData): The RubixData object containing the gas data.

        Returns:
        rubixdata (RubixData): The RubixData object with the gas dispersion factor added to rubixdata.gas.dispersionfactor.
        """
        logger = get_logger(self.config.get("logger", None))
        logger.info("Calculating dispersion factor")
        logger.warning(
            "The dispersion factor for line width currentl only assumes thermal broadening."
        )
        # Constants (https://www.physics.rutgers.edu/~abrooks/342/constants.html)
        k_B = 1.3807 * 10 ** (-16)  # cm2 g s-2 K-1
        c = 2.99792458 * 10**10  # cm s-1
        m_p = 1.6726e-24  # g

        # rubixdata = self.get_emission_peaks(rubixdata)
        rubixdata = self.illustris_gas_temp(rubixdata)
        wavelengths = rubixdata.gas.wave_lines

        dispersionfactor = jnp.sqrt(
            (8 * k_B * rubixdata.gas.temperature * np.log(2)) / (m_p * c**2)
        )
        # dispersionfactor = jnp.ones(len(rubixdata.gas.mass))*10
        dispersionfactor = dispersionfactor[:, None]

        dispersion = dispersionfactor * wavelengths
        rubixdata.gas.dispersionfactor = dispersion
        logger.debug(f"dispersionfactor: {dispersionfactor.shape}")
        logger.debug(f"dispersionfactor: {dispersionfactor}")
        return rubixdata

    def gaussian(self, x, a, b, c):
        """
        Returns a Gaussian function.

        Parameters:
        x (jnp.ndarray): The wavelength range.
        a (float): The amplitude of the Gaussian function.
        b (float): The peak position of the Gaussian function.
        c (float): The standard deviation of the Gaussian function.

        Returns:
        jnp.ndarray: The Gaussian function.
        """
        return a * jnp.exp(-((x - jnp.array(b)) ** 2) / (2 * c**2))

    def get_wavelengthrange(self, steps=1000):
        """
        Returns a range of wavelengths for the spectra dependent on the wavelength range of the emission lines.
        The wavelength range is set to 1000 to 10000 Angstrom, because we currently focus on the optical range.
        This can be easily changed in the future, as long as the Cue model is able to predict the emission lines in the desired wavelength range.
        """

        logger = get_logger(self.config.get("logger", None))
        logger.warning("Wavelengthrange is set to 1000 to 10000 Angstrom.")
        steps = int(steps)
        wave_start = 1e3
        wave_end = 1e4
        wavelengthrange = jnp.linspace(wave_start, wave_end, steps)
        return wavelengthrange

    def continuum_tf(self, theta):
        return cont_predict(theta=theta).nn_predict()

    def calculate_continuum(self, theta):
        """
        Calculate the gas continuum using the provided theta parameters.

        My interpretation of the input: these are the parameters from Table 1 in Li et al. 2024
        gammas: power-law slopes (alpha_HeII, alpha_OII, alpha_HeI and alpha_HI)
        log_L_ratios:   flux ratios of the two bluest segments (log F_OII/F_HeII)
                        flux ratios of the second and third segment (log F_HeI/F_OII)
                        fliux ratios of the two reddest segments (log F_HI/F_HeI)
        log_QH: ionization parameter log U (in Illustris ElectronAbundance)
        n_H: hydrogen density (not in log scale!!!) in 1/cm^3 (in Illustris Denisty)
        log_OH_ratio: oxygen abundance (in Illustris GFM_Metals[4]/GFM_Metals[0])
        log_NO_ratio: nitrogen-to-oxygen ratio (in Illustris GFM_Metals[3]/GFM_Metals[4])
        log_CO_ratio: carbon-to-oxygen ratio (in Illustris GFM_Metals[2]/GFM_Metals[4])

        My interpretation of the output:
        first array: wavelengt in Angstrom
        second array: luminosity in erg/s

        Parameters:
        theta (jnp.ndarray): The theta parameters describing the shape of the ionizing spectrum and the ionizing gas properties, 12 values.

        Returns:
        jnp.ndarray: The predicted continuum.
        continuum[0] is the wavelength in Angstrom
        continuum[1] is the luminosity in erg/s for the continuum in each gas cell
        """
        logger = get_logger(self.config.get("logger", None))
        logger.info("Calculating continuum")
        par = theta
        wavelength_cont, continuum = jax2tf.call_tf(self.continuum_tf)(par)
        # wavelength_cont, continuum = jax2tf.call_tf(cont_predict)(theta)
        # wavelength_cont, continuum = cont_predict(theta).nn_predict()

        # Convert result back to JAX array if needed
        # wave_cont_jax = jnp.array(wavelength_cont)
        # continuum_jax = jnp.array(continuum)
        # logger.debug(
        #    f"wave_cont_jax: {wave_cont_jax.shape}, continuum_jax: {continuum_jax.shape}"
        # )
        # logger.debug(f"wave_cont_jax: {wave_cont_jax}, continuum_jax: {continuum_jax}")
        return wavelength_cont, continuum

    def get_resample_continuum(self, theta):
        """
        Resamples the spectrum of the gas continuum to the new wavelength range using interpolation.
        The new wavelength range is the same for the emission lines.
        We do this step to be able to add the continuum and the emission lines together later.

        Parameters:
        rubixdata (RubixData): The RubixData object containing the gas data.

        original_wavelength (jnp.ndarray): The original wavelength array of continuum.
        continuum (jnp.ndarray): The original spectrum array.
        new_wavelength (jnp.ndarray): The new wavelength array to resample to, which is the same for the emission lines.

        Returns:
        rubixdata.gas.continuum (jnp.ndarray): The resampled wavelength and spectrum array.
        """
        logger = get_logger(self.config.get("logger", None))

        new_wavelength = self.get_wavelengthrange()

        # rubixdata = self.get_continuum_tf(rubixdata)
        # num_mass_elements = len(rubixdata.gas.mass)

        # Define the expected shapes and data types
        # result_shape_dtypes = [
        #    jax.ShapeDtypeStruct(shape=(1841,), dtype=jnp.float32),
        #    jax.ShapeDtypeStruct(shape=(num_mass_elements, 1841), dtype=jnp.float32),
        # ]

        # theta = self.get_theta(rubixdata)
        # theta_tf = tf.convert_to_tensor(theta)
        # logger.debug(f"theta after converting to tensorflow")
        # logger.debug(f"theta: {theta_tf.shape}")
        # logger.debug(f"theta: {theta_tf}")
        # theta = jax.device_get(theta)
        # cue_call_cont = jax.pure_callback(
        # self.calculate_continuum, result_shape_dtypes, theta
        # )
        # cue_call_cont = jax.block_until_ready(cue_call_cont)
        original_wavelength, continuum = self.calculate_continuum(theta)
        # original_wavelength = jax.device_get(original_wavelength)
        # continuum = jax.device_get(continuum)

        # Define the interpolation function
        def interp_fn(continuum_i):
            if original_wavelength.shape != continuum_i.shape:
                raise ValueError(
                    f"Shapes do not match: original_wavelength {original_wavelength.shape}, continuum_i {continuum_i.shape}"
                )
            return jnp.interp(new_wavelength, original_wavelength, continuum_i)

        # Transpose `continuum` to align dimensions properly for interpolation
        # continuum_transposed = continuum.T  # Shape becomes (n_particles, 1841)

        # Vectorize the interpolation function over axis 0
        resampled_continuum = vmap(interp_fn)(continuum)

        # Transpose the result back if needed
        # resampled_continuum = resampled_continuum.T  # Shape becomes (1841, n_particles)

        # rubixdata.gas.continuum = resampled_continuum
        # rubixdata.gas.wave_cont = new_wavelength
        logger.debug(
            f"new_wavelength: {new_wavelength.shape}, resampled_continuum: {resampled_continuum.shape}"
        )
        logger.debug(
            f"new_wavelength: {new_wavelength}, resampled_continuum: {resampled_continuum}"
        )
        return new_wavelength, resampled_continuum

    def lines_tf(self, theta):
        return line_predict(theta=theta).nn_predict()

    def calculate_lines(self, theta):
        """
        Calculate the lines using the provided theta parameters.

        My interpretation of the input: these are the parameters from Table 1 in Li et al. 2024
        gammas: power-law slopes (alpha_HeII, alpha_OII, alpha_HeI and alpha_HI)
        log_L_ratios:   flux ratios of the two bluest segments (log F_OII/F_HeII)
                        flux ratios of the second and third segment (log F_HeI/F_OII)
                        fliux ratios of the two reddest segments (log F_HI/F_HeI)
        log_QH: ionization parameter log U (in Illustris ElectronAbundance)
        n_H: hydrogen density (not in log scale!!!) in 1/cm^3 (in Illustris Denisty)
        log_OH_ratio: oxygen abundance (in Illustris GFM_Metals[4]/GFM_Metals[0])
        log_NO_ratio: nitrogen-to-oxygen ratio (in Illustris GFM_Metals[3]/GFM_Metals[4])
        log_CO_ratio: carbon-to-oxygen ratio (in Illustris GFM_Metals[2]/GFM_Metals[4])

        My interpretation of the output:
        first array: wavelengt in Angstrom
        second array: luminosity in erg/s

        Parameters:
        theta (jnp.ndarray): The theta parameters describing the shape of the ionizing spectrum and the ionizing gas properties, 12 values.

        Returns:
        jnp.ndarray: The predicted emission lines.
        lines[0] is the wavelength in Angstrom
        lines[1] is the luminosity in erg/s for the emission lines in each gas cell
        """
        logger = get_logger(self.config.get("logger", None))
        logger.warning(
            "Calculating emission lines assumes that we trust the outcome of the Cue model (Li et al. 2024)."
        )
        # theta = np.array(theta)

        # Call the non-JAX-compatible function
        # print(f"theta nefore passed to tf function: {theta}")
        # print(f"theta shape before passed to tf function: {theta.shape}")
        # wavelength, nn_spectra = jax2tf.call_tf(line_predict)(theta)
        # wavelength, nn_spectra = line_predict(theta).nn_predict()
        # wavelength, nn_spectra = jax2tf.call_tf(self.lines_tf)(1000, theta)
        par = theta
        wavelength_lines, lines = jax2tf.call_tf(self.lines_tf)(par)

        # Convert result back to JAX array if needed
        # wave_line_jax = jnp.array(wavelength)
        # lines_jax = jnp.array(nn_spectra)
        # lines_jax = jnp.nan_to_num(lines_jax, posinf=0.0, neginf=0.0)
        # logger.debug(
        #    f"wave_line_jax: {wave_line_jax.shape}, lines_jax: {lines_jax.shape}"
        # )
        # logger.debug(f"wave_line_jax: {wave_line_jax}, lines_jax: {lines_jax}")

        return wavelength_lines, lines

    def get_emission_lines(self, rubixdata):
        """
        Returns the spectra of the gas in the galaxy according to the Cue lookup table.
        The spectra takes the luminosity and dispersion factor of each gas cell and calculates the Gaussian emission line and adds all up for each gas cell.

        Parameters:
        rubixdata (RubixData): The RubixData object containing the gas data.

        Returns:
        rubixdata (RubixData): The RubixData object with the gas emission spectra added to rubixdata.gas.emission_spectra.
        """
        logger = get_logger(self.config.get("logger", None))
        logger.info("Calculating gas emission lines")
        # get wavelengths of lookup and wavelengthrange of telescope

        # rubixdata = self.get_emission_peaks(rubixdata)
        # wavelengths = rubixdata.gas.wave_lines

        # number_mass_elements = len(rubixdata.gas.mass)

        # result_shape_dtypes_lines = [
        #    jax.ShapeDtypeStruct(shape=(138,), dtype=jnp.float32),
        #    jax.ShapeDtypeStruct(shape=(number_mass_elements, 138), dtype=jnp.float32),
        # ]

        theta = self.get_theta(rubixdata)
        # theta_tf = tf.convert_to_tensor(theta)
        # theta_numpy = np.array(theta)
        # if type(theta_numpy) != np.ndarray:
        #    raise TypeError("Expected theta to be a NumPy array.")
        # theta = jax.device_get(theta)
        # cue_call_lines = jax.pure_callback(
        #    self.calculate_lines, result_shape_dtypes_lines, theta
        # )
        # cue_call_lines = self.calculate_lines(theta)
        # logger.debug(f"cue_call_lines: {cue_call_lines}")
        # cue_call_lines = jax.block_until_ready(cue_call_lines)
        wavelengths, emission_peaks = self.calculate_lines(theta)
        # wavelengths = jax.device_get(wavelengths)
        # emission_peaks = jax.device_get(emission_peaks)
        logger.debug(f"wavelengths after jax.device_get: {wavelengths}")
        logger.debug(f"emission_peaks after jax.device_get: {emission_peaks}")
        rubixdata.gas.wave_lines = wavelengths
        rubixdata.gas.emission_peaks = emission_peaks

        wavelengthrange = self.get_wavelengthrange()
        # update rubixdata with temperature, dispersionfactor and luminosity
        rubixdata = self.illustris_gas_temp(rubixdata)
        rubixdata = self.dispersionfactor(rubixdata)

        spectra_all = []

        # Define a function to compute the Gaussian for a single set of parameters
        def compute_gaussian(l, wl, fwhm):
            return self.gaussian(wavelengthrange, l, wl, fwhm)

        # Vectorize the compute_gaussian function
        vmap_gaussian = vmap(compute_gaussian, in_axes=(0, 0, 0))

        # Define a function to compute the spectrum for a single particle
        def compute_spectrum(luminosity, fwhm):
            gaussians = vmap_gaussian(luminosity, wavelengths, fwhm)
            return jnp.sum(gaussians, axis=0)

        # Vectorize the compute_spectrum function over all particles
        vmap_spectrum = vmap(compute_spectrum, in_axes=(0, 0))

        # Compute the spectra for all particles
        spectra_all = vmap_spectrum(
            rubixdata.gas.emission_peaks, rubixdata.gas.dispersionfactor
        )

        # Store the spectra and wavelength range in rubixdata
        rubixdata.gas.emission_spectra = spectra_all
        rubixdata.gas.wavelengthrange = wavelengthrange
        logger.debug(
            f"wavelengthrange: {wavelengthrange.shape}, spectra_all: {spectra_all.shape}"
        )
        logger.debug(f"wavelengthrange: {wavelengthrange}, spectra_all: {spectra_all}")
        return rubixdata

    def get_gas_emission(self, rubixdata):
        """ "
        Returns the added spectrum of gas contnuum and emission lines, both from the Cue lookup

        Parameters:
        rubixdata (RubixData): The RubixData object containing the gas data.

        Returns:
        rubixdata (RubixData): The RubixData object with the gas emission added to rubixdata.gas.spectra.
        """
        logger = get_logger(self.config.get("logger", None))
        logger.info("Calculating gas emission (continuum and emission lines combined)")

        rubixdata = self.get_emission_lines(rubixdata)
        rubixdata = self.get_resample_continuum(rubixdata)

        continuum = rubixdata.gas.continuum
        emission_lines = rubixdata.gas.emission_spectra

        gas_emission = continuum + emission_lines

        gas_emission_cleaned = jnp.nan_to_num(
            gas_emission, posinf=0.0, neginf=0.0, nan=0.0
        )

        rubixdata.gas.spectra = gas_emission_cleaned

        logger.debug(
            f"continuum: {continuum.shape}, emission_lines: {emission_lines.shape}"
        )
        logger.debug(f"gas_emission: {gas_emission.shape}")
        logger.debug(f"gas_emission_cleaned: {gas_emission_cleaned.shape}")
        return rubixdata

    def get_gas_emission_flux(self, rubixdata):
        logger = get_logger(self.config.get("logger", None))
        """
        Converts the gas emission spectra to flux.
        Because of very small and very large values, we have to multiply the luminosity and factor with a factor.
        Flux in erg/s/cm^2/Angstrom.

        Parameters:
        rubixdata (RubixData): The RubixData object containing the gas data.

        Returns:
        rubixdata (RubixData): The RubixData object with the gas emission flux added to rubixdata.gas.spectra.
        """
        logger = get_logger(self.config.get("logger", None))
        logger.info("Calculating gas emission flux from luminosity")

        rubixdata = self.get_gas_emission(rubixdata)

        # Convert luminosity to flux using the preprocessed factor
        luminosity = rubixdata.gas.spectra * 1e-30
        luminosity = luminosity * 1e-20

        flux = luminosity * self.factor

        rubixdata.gas.spectra = flux

        logger.debug(f"luminosity: {luminosity.shape}, flux: {flux.shape}")
        logger.debug(f"luminosity: {luminosity}, flux: {flux}")

        return rubixdata