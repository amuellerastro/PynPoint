"""
Functions for analysis of a planet signal.
"""

import math

import numpy as np

from photutils import aperture_photometry, CircularAperture
from scipy.stats import t


def false_alarm(image, x_pos, y_pos, size, ignore):
    """
    Function for the formal t-test for high-contrast imaging at small working angles, as well as
    the related false positive fraction (Mawet et al. 2014).

    :param image: Input image.
    :type image: ndarray
    :param x_pos: Position (pix) along the x-axis.
    :type x_pos: float
    :param y_pos: Position (pix) along the y-axis.
    :type y_pos: float
    :param size: Aperture radius (pix).
    :type size: float
    :param ignore: Ignore neighboring aperture for the noise.
    :type ignore: bool

    :return: Noise level, SNR, FPF
    :rtype: float, float, float
    """

    center = (np.size(image, 0)/2., np.size(image, 1)/2.)
    radius = math.sqrt((center[0]-y_pos)**2.+(center[1]-x_pos)**2.)

    num_ap = int(math.pi*radius/size)
    ap_theta = np.linspace(0, 2.*math.pi, num_ap, endpoint=False)

    if ignore:
        num_ap -= 2
        ap_theta = np.delete(ap_theta, [1, np.size(ap_theta)-1])

    if num_ap < 3:
        raise ValueError("Number of apertures (num_ap=%s) is too small to calculate the "
                         "false positive fraction. Increase the lower limit of the "
                         "separation argument." % num_ap)

    ap_phot = np.zeros(num_ap)
    for i, theta in enumerate(ap_theta):
        x_tmp = center[1] + (x_pos-center[1])*math.cos(theta) - \
                            (y_pos-center[0])*math.sin(theta)
        y_tmp = center[0] + (x_pos-center[1])*math.sin(theta) + \
                            (y_pos-center[0])*math.cos(theta)

        aperture = CircularAperture((x_tmp, y_tmp), size)
        phot_table = aperture_photometry(image, aperture, method='exact')
        ap_phot[i] = phot_table['aperture_sum']

    noise = np.std(ap_phot[1:]) * math.sqrt(1.+1./float(num_ap-1))
    t_test = (ap_phot[0] - np.mean(ap_phot[1:])) / noise

    return noise, t_test, 1. - t.cdf(t_test, num_ap-2)

def student_fpf(sigma, radius, size, ignore):
    """
    Function to calculate the false positive fraction for a given sigma level (Mawet et al. 2014).
    """

    num_ap = int(math.pi*radius/size)
    if ignore:
        num_ap -= 2

    return 1. - t.cdf(sigma, num_ap-2, loc=0., scale=1.)
