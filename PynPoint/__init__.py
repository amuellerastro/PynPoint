import warnings

from PynPoint.Core.Pypeline import Pypeline
from PynPoint.Wrapper.BasisWrapper import BasisWrapper as basis
from PynPoint.Wrapper.ImageWrapper import ImageWrapper as images
from PynPoint.Wrapper.ResidualsWrapper import ResidualsWrapper as residuals

warnings.filterwarnings("ignore", message="numpy.dtype size changed")

__author__ = 'Tomas Stolker, Markus Bonse, Sascha Quanz, and Adam Amara'
__copyright__ = '2014-2018, ETH Zurich'
__license__ = 'GPL'
__version__ = '0.4.0'
__maintainer__ = 'Tomas Stolker'
__email__ = 'tomas.stolker@phys.ethz.ch'
__status__ = 'Development'
