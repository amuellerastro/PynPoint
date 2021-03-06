"""
Modules for locating, aligning, and centering of the star.
"""

import math

import warnings
import numpy as np
import cv2

from skimage.feature import register_translation
from skimage.transform import rescale
from scipy.ndimage import fourier_shift
from scipy.ndimage import shift
from scipy.optimize import curve_fit

from PynPoint.Core.Processing import ProcessingModule
from PynPoint.Util.ModuleTools import memory_frames


class StarExtractionModule(ProcessingModule):
    """
    Module to locate the position of the star in each image and to crop all the
    images around this position.
    """

    def __init__(self,
                 name_in="star_cutting",
                 image_in_tag="im_arr",
                 image_out_tag="im_arr_crop",
                 index_out_tag=None,
                 image_size=2.,
                 fwhm_star=0.2,
                 position=None,
                 **kwargs):
        """
        Constructor of StarExtractionModule.

        :param name_in: Unique name of the module instance.
        :type name_in: str
        :param image_in_tag: Tag of the database entry that is read as input.
        :type image_in_tag: str
        :param image_out_tag: Tag of the database entry that is written as output. Should be
                              different from *image_in_tag*. If *image_out_tag* and/or *image_size*
                              is set to None then only the STAR_POSITION attributes will be written
                              to *image_in_tag* and *image_out_tag* is not used.
        :type image_out_tag: str
        :param index_out_tag: List with image indices for which the image size is too large to
                              be cropped around the brightest pixel. No data is written if set
                              to None.
        :type index_out_tag: str
        :param image_size: Cropped image size (arcsec). If *image_out_tag* and/or *image_size* is
                           set to None then only the STAR_POSITION attributes will be written to
                           *image_in_tag* and *image_out_tag* is not used.
        :type image_size: float
        :param fwhm_star: Full width at half maximum (arcsec) of the Gaussian kernel that is used
                          to convolve the images.
        :type fwhm_star: float
        :param position: Subframe that is selected to search for the star. The tuple can contain a
                         single position (pix) and size (arcsec) as (pos_x, pos_y, size), or the
                         position and size can be defined for each image separately in which case
                         the tuple should be 2D (nframes x 3). Setting *position* to None will use
                         the full image to search for the star. If *position=(None, None, size)*
                         then the center of the image will be used.
        :type position: tuple, float

        :param \**kwargs:
            See below.

        :Keyword arguments:
             * **position_out_tag** (*str*) -- Tag of the database entry to which the STAR_POSITION
                                               attributes are written. The *image_in_tag* is used
                                               if set to None.

        :return: None
        """

        if "position_out_tag" in kwargs:
            position_out_tag = kwargs["position_out_tag"]
        else:
            position_out_tag = None

        super(StarExtractionModule, self).__init__(name_in)

        self.m_image_in_port = self.add_input_port(image_in_tag)

        if image_out_tag is None:
            self.m_image_out_port = None
        else:
            self.m_image_out_port = self.add_output_port(image_out_tag)

        if index_out_tag is None:
            self.m_index_out_port = None
        else:
            self.m_index_out_port = self.add_output_port(index_out_tag)

        if position_out_tag is None:
            self.m_position_out_port = self.add_output_port(image_in_tag)
        else:
            self.m_position_out_port = self.add_output_port(position_out_tag)

        self.m_image_size = image_size
        self.m_fwhm_star = fwhm_star
        self.m_position = position

        self.m_count = 0

    def run(self):
        """
        Run method of the module. Locates the position of the star (only pixel precision) by
        selecting the highest pixel value. A Gaussian kernel with a FWHM similar to the PSF is
        used to smooth away the contribution of bad pixels which may have higher values than the
        peak of the PSF. Images are cropped and written to an output port. The position of the
        star is attached to the input images as the non-static attribute STAR_POSITION (y, x).

        :return: None
        """

        pixscale = self.m_image_in_port.get_attribute("PIXSCALE")

        if self.m_position is not None:
            self.m_position = np.asarray(self.m_position)

            if self.m_position.ndim == 2 and \
                    self.m_position.shape[0] != self.m_image_in_port.get_shape()[0]:
                raise ValueError("Either a single 'position' should be specified or an array "
                                 "equal in size to the number of images in 'image_in_tag'.")

            if self.m_position[0] is None and self.m_position[1] is None:
                npix = self.m_image_in_port.get_shape()[1]
                self.m_position[0] = npix/2.
                self.m_position[1] = npix/2.

        if self.m_image_size is not None:
            psf_radius = int((self.m_image_size/2.)/pixscale)

        self.m_fwhm_star /= pixscale
        self.m_fwhm_star = int(self.m_fwhm_star)

        star = []
        index = []

        def _crop_image(image):
            sigma = self.m_fwhm_star/math.sqrt(8.*math.log(2.))
            kernel = (self.m_fwhm_star*2 + 1, self.m_fwhm_star*2 + 1)

            if self.m_position is None:
                subimage = image

            elif self.m_position[2] is None:
                pos_x = self.m_position[0]
                pos_y = self.m_position[1]
                subimage = image
                width = np.shape(image)[0]

            else:
                if self.m_position.ndim == 1:
                    pos_x = self.m_position[0]
                    pos_y = self.m_position[1]
                    width = self.m_position[2]/pixscale

                    if pos_x > self.m_image_in_port.get_shape()[1] or \
                            pos_y > self.m_image_in_port.get_shape()[2]:
                        raise ValueError('The specified position is outside the image.')

                elif self.m_position.ndim == 2:
                    pos_x = self.m_position[self.m_count, 0]
                    pos_y = self.m_position[self.m_count, 1]
                    width = self.m_position[self.m_count, 2]/pixscale

                if pos_y <= width/2. or pos_x <= width/2. \
                        or pos_y+width/2. >= self.m_image_in_port.get_shape()[2]\
                        or pos_x+width/2. >= self.m_image_in_port.get_shape()[1]:
                    warnings.warn("The region for the star extraction exceeds the image.")

                subimage = image[int(pos_y-width/2.):int(pos_y+width/2.),
                                 int(pos_x-width/2.):int(pos_x+width/2.)]

            im_smooth = cv2.GaussianBlur(subimage, kernel, sigma)

            # argmax[0] is the y position and argmax[1] is the x position
            argmax = np.asarray(np.unravel_index(im_smooth.argmax(), im_smooth.shape))

            if self.m_position is not None:
                argmax[0] += pos_y-width/2.
                argmax[1] += pos_x-width/2.

            if self.m_image_size is not None:
                if argmax[0] <= psf_radius or argmax[1] <= psf_radius \
                        or argmax[0] + psf_radius >= image.shape[0] \
                        or argmax[1] + psf_radius >= image.shape[1]:

                    warnings.warn("PSF size is too large to crop the image around the brightest "
                                  "pixel (image index = "+str(self.m_count)+", pixel [x, y] = "
                                  +str([argmax[1]]+[argmax[0]])+"). Using the center of the image "
                                  "instead.")

                    index.append(self.m_count)

                    argmax = [np.size(image, 0)/2., np.size(image, 0)/2.]

                im_crop = image[int(argmax[0] - psf_radius):int(argmax[0] + psf_radius),
                                int(argmax[1] - psf_radius):int(argmax[1] + psf_radius)]

            star.append(argmax)

            self.m_count += 1

            if self.m_image_size is not None:
                return im_crop

        self.apply_function_to_images(_crop_image,
                                      self.m_image_in_port,
                                      self.m_image_out_port,
                                      "Running StarExtractionModule...")

        self.m_position_out_port.add_attribute("STAR_POSITION", np.asarray(star), static=False)

        if self.m_index_out_port is not None:
            self.m_index_out_port.set_all(np.transpose(np.asarray(index)))
            self.m_index_out_port.copy_attributes_from_input_port(self.m_image_in_port)
            self.m_index_out_port.add_history_information("Star extract", "maximum")

        if self.m_image_size is not None and self.m_image_out_port is not None:
            self.m_image_out_port.copy_attributes_from_input_port(self.m_image_in_port)
            self.m_image_out_port.add_history_information("Star extract", "maximum")

        self.m_position_out_port.close_port()


class StarAlignmentModule(ProcessingModule):
    """
    Module to align the images with a cross-correlation in Fourier space.
    """

    def __init__(self,
                 name_in="star_align",
                 image_in_tag="im_arr",
                 ref_image_in_tag=None,
                 image_out_tag="im_arr_aligned",
                 interpolation="spline",
                 accuracy=10,
                 resize=None,
                 num_references=10):
        """
        Constructor of StarAlignmentModule.

        :param name_in: Unique name of the module instance.
        :type name_in: str
        :param image_in_tag: Tag of the database entry with the stack of images that is read as
                             input.
        :type image_in_tag: str
        :param ref_image_in_tag: Tag of the database entry with the reference image(s)
                                 that are read as input. If it is set to None, a random
                                 subsample of *num_references* elements of *image_in_tag*
                                 is taken as reference image(s)
        :type ref_image_in_tag: str
        :param image_out_tag: Tag of the database entry with the images that are written as
                              output.
        :type image_out_tag: str
        :param interpolation: Type of interpolation that is used for shifting the images (spline,
                              bilinear, or fft).
        :type interpolation: str
        :param accuracy: Upsampling factor for the cross-correlation. Images will be registered
                         to within 1/accuracy of a pixel.
        :type accuracy: float
        :param resize: Scaling factor for the up/down-sampling before the images are shifted.
        :type resize: float
        :param num_references: Number of reference images for the cross-correlation.
        :type num_references: int

        :return: None
        """

        super(StarAlignmentModule, self).__init__(name_in)

        self.m_image_in_port = self.add_input_port(image_in_tag)
        self.m_image_out_port = self.add_output_port(image_out_tag)

        if ref_image_in_tag is not None:
            self.m_ref_image_in_port = self.add_input_port(ref_image_in_tag)
        else:
            self.m_ref_image_in_port = None

        self.m_interpolation = interpolation
        self.m_accuracy = accuracy
        self.m_resize = resize
        self.m_num_references = num_references

    def run(self):
        """
        Run method of the module. Applies a cross-correlation of the input images with respect to
        a stack of reference images, rescales the image dimensions, and shifts the images to a
        common center.

        :return: None
        """

        if self.m_ref_image_in_port is not None:
            im_dim = self.m_ref_image_in_port.get_ndim()

            if im_dim == 3:
                if self.m_ref_image_in_port.get_shape()[0] > self.m_num_references:
                    ref_images = self.m_ref_image_in_port[np.sort(
                        np.random.choice(self.m_ref_image_in_port.get_shape()[0],
                                         self.m_num_references,
                                         replace=False)), :, :]

                else:
                    ref_images = self.m_ref_image_in_port.get_all()
                    self.m_num_references = self.m_ref_image_in_port.get_shape()[0]

            elif im_dim == 2:
                ref_images = np.array([self.m_ref_image_in_port.get_all(), ])
                self.m_num_references = 1

            else:
                raise ValueError("Reference images need to be 2D or 3D.")

        else:
            random = np.random.choice(self.m_image_in_port.get_shape()[0],
                                      self.m_num_references,
                                      replace=False)
            sort = np.sort(random)
            ref_images = self.m_image_in_port[sort, :, :]

        def _align_image(image_in):
            offset = np.array([0., 0.])

            for i in range(self.m_num_references):
                tmp_offset, _, _ = register_translation(ref_images[i, :, :],
                                                        image_in,
                                                        upsample_factor=self.m_accuracy)
                offset += tmp_offset

            offset /= float(self.m_num_references)
            if self.m_resize is not None:
                offset *= self.m_resize

            if self.m_resize is not None:
                sum_before = np.sum(image_in)
                tmp_image = rescale(image=np.asarray(image_in, dtype=np.float64),
                                    scale=(self.m_resize, self.m_resize),
                                    order=5,
                                    mode="reflect")
                sum_after = np.sum(tmp_image)

                # Conserve flux because the rescale function normalizes all values to [0:1].
                tmp_image = tmp_image*(sum_before/sum_after)

            else:
                tmp_image = image_in

            if self.m_interpolation == "spline":
                tmp_image = shift(tmp_image, offset, order=5)

            elif self.m_interpolation == "bilinear":
                tmp_image = shift(tmp_image, offset, order=1)

            elif self.m_interpolation == "fft":
                tmp_image_spec = fourier_shift(np.fft.fftn(tmp_image), offset)
                tmp_image = np.fft.ifftn(tmp_image_spec).real

            else:
                raise ValueError("Interpolation should be spline, bilinear, or fft.")

            return tmp_image

        self.apply_function_to_images(_align_image,
                                      self.m_image_in_port,
                                      self.m_image_out_port,
                                      "Running StarAlignmentModule...")

        self.m_image_out_port.copy_attributes_from_input_port(self.m_image_in_port)

        if self.m_resize is not None:
            pixscale = self.m_image_in_port.get_attribute("PIXSCALE")
            self.m_image_out_port.add_attribute("PIXSCALE", pixscale/self.m_resize)

        if self.m_resize is None:
            history = "cross-correlation, no upsampling"
        else:
            history = "cross-correlation, upsampling factor =" + str(self.m_resize)
        self.m_image_out_port.add_history_information("PSF alignment", history)
        self.m_image_out_port.close_port()


class StarCenteringModule(ProcessingModule):
    """
    Module for centering the star by fitting a 2D Gaussian profile.
    """

    def __init__(self,
                 name_in="centering",
                 image_in_tag="im_arr",
                 image_out_tag="im_center",
                 mask_out_tag=None,
                 fit_out_tag="center_fit",
                 method="full",
                 interpolation="spline",
                 radius=0.1,
                 sign="positive",
                 **kwargs):
        """
        Constructor of StarCenteringModule.

        :param name_in: Unique name of the module instance.
        :type name_in: str
        :param image_in_tag: Tag of the database entry with images that are read as input.
        :type image_in_tag: str
        :param image_out_tag: Tag of the database entry with the centered images that are written
                              as output. Should be different from *image_in_tag*. Data is not
                              written when set to *None*.
        :type image_out_tag: str
        :param mask_out_tag: Tag of the database entry with the masked images that are written as
                             output. The unmasked part of the images is used for the fit. Data is
                             not written when set to *None*.
        :type mask_out_tag: str
        :param fit_out_tag: Tag of the database entry with the best-fit results of the 2D Gaussian
                            fit and the 1-sigma errors. Data is written in the following format:
                            x offset (arcsec), x offset error (arcsec), y offset (arcsec), y offset
                            error (arcsec), FWHM major axis (arcsec), FWHM major axis error
                            (arcsec), FWHM minor axis (arcsec), FWHM minor axis error
                            (arcsec), amplitude (counts), amplitude error (counts), angle (deg),
                            angle error (deg) measured in counterclockwise direction with respect
                            to the upward direction (i.e., East of North).
        :type fit_out_tag: str
        :param method: Fit and shift all the images individually ("full") or only fit the mean of
                       the cube and shift all images to that location ("mean"). The "mean" method
                       could be used after running the StarAlignmentModule.
        :type method: str
        :param interpolation: Type of interpolation that is used for shifting the images (spline,
                              bilinear, or fft).
        :type interpolation: str
        :param radius: Radius (arcsec) around the center of the image beyond which pixels are
                       neglected with the fit. The radius is centered on the position specified
                       in *guess*, which is the center of the image by default.
        :type radius: float
        :param sign: Fit a *"positive"* or *"negative"* Gaussian. A negative Gaussian can be
                     used to center coronagraphic data in which a dark hole is present.
        :type sign: str
        :param \**kwargs:
            See below.

        :Keyword arguments:
             * **guess** (*tuple*) -- Tuple with the initial parameter values for the least
                                      squares fit: center x (pix), center y (pix), FWHM x (pix),
                                      FWHM y (pix), amplitude (counts), angle (deg). Note that the
                                      center positions are relative to the image center.

        :return: None
        """

        if "guess" in kwargs:
            self.m_guess = kwargs["guess"]
        else:
            self.m_guess = (0., 0., 1., 1., 1., 0.)

        super(StarCenteringModule, self).__init__(name_in)

        self.m_image_in_port = self.add_input_port(image_in_tag)

        if image_out_tag is None:
            self.m_image_out_port = None
        else:
            self.m_image_out_port = self.add_output_port(image_out_tag)

        if mask_out_tag is None:
            self.m_mask_out_port = None
        else:
            self.m_mask_out_port = self.add_output_port(mask_out_tag)

        self.m_fit_out_port = self.add_output_port(fit_out_tag)

        self.m_method = method
        self.m_interpolation = interpolation
        self.m_radius = radius
        self.m_sign = sign
        self.m_count = 0

    def run(self):
        """
        Run method of the module. Uses a non-linear least squares (Levenberg-Marquardt) to fit the
        the individual images or the mean of the stack with a 2D Gaussian profile, shifts the
        images with subpixel precision, and writes the centered images and the fitting results. The
        fitting results contain zeros in case the algorithm could not converge.

        :return: None
        """

        if self.m_image_out_port is not None:
            self.m_image_out_port.del_all_data()
            self.m_image_out_port.del_all_attributes()

        self.m_fit_out_port.del_all_data()
        self.m_fit_out_port.del_all_attributes()

        if self.m_mask_out_port is not None:
            self.m_mask_out_port.del_all_data()
            self.m_mask_out_port.del_all_attributes()

        memory = self._m_config_port.get_attribute("MEMORY")
        pixscale = self.m_image_in_port.get_attribute("PIXSCALE")

        def _initialize():
            if self.m_radius is not None:
                self.m_radius /= pixscale

            ndim = self.m_image_in_port.get_ndim()

            if ndim == 2:
                nimages = 1
            elif ndim == 3:
                nimages = self.m_image_in_port.get_shape()[0]

            npix = self.m_image_in_port.get_shape()[1]

            if npix/2.+self.m_guess[0]+self.m_radius > npix or \
                    npix/2.+self.m_guess[1]+self.m_radius > npix or \
                    npix/2.+self.m_guess[1]-self.m_radius < 0. or \
                    npix/2.+self.m_guess[1]-self.m_radius < 0.:
                raise ValueError("Mask radius extends beyond the size of the image.")

            frames = memory_frames(memory, nimages)

            return ndim, nimages, npix, frames

        def _2d_gaussian((x_grid, y_grid, rr_ap_1d, npix),
                         x_center,
                         y_center,
                         fwhm_x,
                         fwhm_y,
                         amp,
                         theta):
            rr_ap = np.reshape(rr_ap_1d, (npix, npix))

            xx_grid, yy_grid = np.meshgrid(x_grid, y_grid)
            x_diff = xx_grid - x_center
            y_diff = yy_grid - y_center

            sigma_x = fwhm_x/math.sqrt(8.*math.log(2.))
            sigma_y = fwhm_y/math.sqrt(8.*math.log(2.))

            a_gauss = 0.5 * ((np.cos(theta)/sigma_x)**2 + (np.sin(theta)/sigma_y)**2)
            b_gauss = 0.5 * ((np.sin(2.*theta)/sigma_x**2) - (np.sin(2.*theta)/sigma_y**2))
            c_gauss = 0.5 * ((np.sin(theta)/sigma_x)**2 + (np.cos(theta)/sigma_y)**2)

            gaussian = amp*np.exp(-(a_gauss*x_diff**2 + b_gauss*x_diff*y_diff + c_gauss*y_diff**2))
            gaussian = gaussian[rr_ap < self.m_radius]

            return np.ravel(gaussian)

        def _least_squares(image):
            npix = image.shape[0]

            if npix%2 == 0:
                x_grid = y_grid = np.linspace(-npix/2+0.5, npix/2-0.5, npix)
                x_ap = np.linspace(-npix/2+0.5-self.m_guess[0], npix/2-0.5-self.m_guess[0], npix)
                y_ap = np.linspace(-npix/2+0.5-self.m_guess[1], npix/2-0.5-self.m_guess[1], npix)

            elif npix%2 == 1:
                x_grid = y_grid = np.linspace(-(npix-1)/2, (npix-1)/2, npix)
                x_ap = np.linspace(-(npix-1)/2-self.m_guess[0], (npix-1)/2-self.m_guess[0], npix)
                y_ap = np.linspace(-(npix-1)/2-self.m_guess[1], (npix-1)/2-self.m_guess[1], npix)

            xx_ap, yy_ap = np.meshgrid(x_ap, y_ap)
            rr_ap = np.sqrt(xx_ap**2+yy_ap**2)
            rr_ap_1d = np.ravel(rr_ap)

            if self.m_mask_out_port is not None:
                mask = np.copy(image)
                mask[rr_ap > self.m_radius] = 0.

                if self.m_method == "mean":
                    self.m_mask_out_port.set_all(mask)
                elif self.m_method == "full":
                    self.m_mask_out_port.append(mask, data_dim=3)

            if self.m_sign == "negative":
                image = -image + np.abs(np.min(-image))

            image = image[rr_ap < self.m_radius]

            try:
                popt, pcov = curve_fit(_2d_gaussian,
                                       (x_grid, y_grid, rr_ap_1d, npix),
                                       image,
                                       p0=self.m_guess,
                                       sigma=None,
                                       method='lm')

                perr = np.sqrt(np.diag(pcov))

            except RuntimeError:
                popt = np.zeros(6)
                perr = np.zeros(6)
                self.m_count += 1

            res = np.asarray((popt[0]*pixscale, perr[0]*pixscale,
                              popt[1]*pixscale, perr[1]*pixscale,
                              popt[2]*pixscale, perr[2]*pixscale,
                              popt[3]*pixscale, perr[3]*pixscale,
                              popt[4], perr[4],
                              math.degrees(popt[5])%360., math.degrees(perr[5])))

            self.m_fit_out_port.append(res, data_dim=2)

            return popt

        def _centering(image,
                       fit):

            if self.m_method == "full":
                popt = _least_squares(np.copy(image))

            elif self.m_method == "mean":
                popt = fit

            if self.m_interpolation == "spline":
                im_center = shift(image, (-popt[1], -popt[0]), order=5)

            elif self.m_interpolation == "bilinear":
                im_center = shift(image, (-popt[1], -popt[0]), order=1)

            elif self.m_interpolation == "fft":
                fft_shift = fourier_shift(np.fft.fftn(image), (-popt[1], -popt[0]))
                im_center = np.fft.ifftn(fft_shift).real

            return im_center

        ndim, nimages, npix, frames = _initialize()

        if self.m_method == "full":
            fit = None

        elif self.m_method == "mean":
            im_mean = np.zeros((npix, npix))

            if ndim == 2:
                im_mean += self.m_image_in_port[:, :]

            elif ndim == 3:
                for i, _ in enumerate(frames[:-1]):
                    im_mean += np.sum(self.m_image_in_port[frames[i]:frames[i+1], ], axis=0)

                im_mean /= float(nimages)

            fit = _least_squares(im_mean)

        self.apply_function_to_images(_centering,
                                      self.m_image_in_port,
                                      self.m_image_out_port,
                                      "Running StarCenteringModule...",
                                      func_args=(fit, ))

        if self.m_count > 0:
            print "2D Gaussian fit could not converge on %s image(s). [WARNING]" % self.m_count

        if self.m_image_out_port is not None:
            self.m_image_out_port.add_history_information("Centering", "2D Gaussian fit")
            self.m_image_out_port.copy_attributes_from_input_port(self.m_image_in_port)

        self.m_fit_out_port.add_history_information("Centering", "2D Gaussian fit")
        self.m_fit_out_port.copy_attributes_from_input_port(self.m_image_in_port)

        if self.m_mask_out_port is not None:
            self.m_mask_out_port.add_history_information("Centering", "2D Gaussian fit")
            self.m_mask_out_port.copy_attributes_from_input_port(self.m_image_in_port)

        self.m_fit_out_port.close_port()


class ShiftImagesModule(ProcessingModule):
    """
    Module for shifting of an image.
    """

    def __init__(self,
                 shift_xy,
                 name_in="shift",
                 image_in_tag="im_arr",
                 image_out_tag="im_arr_shifted"):
        """
        Constructor of ShiftImagesModule.

        :param shift_xy: Tuple (delta_x, delta_y) with the shift (pix) in both directions.
        :type shift_xy: tuple, float
        :param name_in: Unique name of the module instance.
        :type name_in: str
        :param image_in_tag: Tag of the database entry that is read as input.
        :type image_in_tag: str
        :param image_out_tag: Tag of the database entry that is written as output. Should be
                              different from *image_in_tag*.
        :type image_out_tag: str

        :return: None
        """

        super(ShiftImagesModule, self).__init__(name_in=name_in)

        self.m_image_in_port = self.add_input_port(image_in_tag)
        self.m_image_out_port = self.add_output_port(image_out_tag)

        self.m_shift = shift_xy

    def run(self):
        """
        Run method of the module. Shifts an image with a fifth order spline interpolation.

        :return: None
        """

        def _image_shift(image_in):
            return shift(image_in, (self.m_shift[1], self.m_shift[0]), order=5)

        self.apply_function_to_images(_image_shift,
                                      self.m_image_in_port,
                                      self.m_image_out_port,
                                      "Running ShiftImagesModule...")

        self.m_image_out_port.add_history_information("Images shifted", str(self.m_shift))
        self.m_image_out_port.copy_attributes_from_input_port(self.m_image_in_port)
        self.m_image_out_port.close_port()
