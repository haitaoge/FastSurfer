import optparse
import sys
import numpy as np
import nibabel as nib

HELPTEXT = """
Script to conform an MRI brain image to UCHAR, RAS orientation, and 1mm isotropic voxels


USAGE:
conform.py  -i <input> -o <output>


Dependencies:
    Python 3.5

    Numpy
    http://www.numpy.org

    Nibabel to read and write FreeSurfer data
    http://nipy.org/nibabel/


Original Author: Martin Reuter
Date: Jul-09-2019

"""

h_input = 'path to input image'
h_output = 'path to ouput image'
h_oder = 'order of interpolation (0=nearest,1=linear(default),2=quadratic,3=cubic)'


def options_parse():
    """
    Command line option parser for reduce_to_aparc.py
    """
    parser = optparse.OptionParser(version='$Id: conform.py,v 1.0 2019/07/19 10:52:08 mreuter Exp $',
                                   usage=HELPTEXT)
    parser.add_option('--input', '-i', dest='input', help=h_input)
    parser.add_option('--output', '-o', dest='output', help=h_output)
    parser.add_option('--order', dest='order', help=h_output, type="int", default=1)
    (fin_options, args) = parser.parse_args()
    if fin_options.input is None or fin_options.output is None:
        sys.exit('ERROR: Please specify input and output images')
    return fin_options


def map_image(img, out_affine, out_shape, ras2ras=np.array([[1.0, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]),
              order=1):
    """
    Function to map image to new voxel space (RAS orientation)

    :param nibabel.MGHImage img: the src 3D image with data and affine set
    :param np.ndarray out_affine: trg image affine
    :param np.ndarray out_shape: the trg shape information
    :param np.ndarray ras2ras: ras2ras an additional maping that should be applied (default=id to just reslice)
    :param int order: order of interpolation (0=nearest,1=linear(default),2=quadratic,3=cubic)
    :return: mapped Image data array
    """
    from scipy.ndimage import affine_transform
    from numpy.linalg import inv

    # compute vox2vox from src to trg
    vox2vox = inv(out_affine) @ ras2ras @ img.affine

    # here we apply the inverse vox2vox (to pull back the src info to the target image)
    new_data = affine_transform(img.get_data(), inv(vox2vox), output_shape=out_shape, order=order)
    return new_data


def getscale(data, dst_min, dst_max, f_low=0.0, f_high=0.999):
    """
    Function to get offset and scale of image intensities to robustly rescale to range dst_min..dst_max.
    Equivalent to how mri_convert conforms images.

    :param np.ndarray data: Image data (intensity values)
    :param float dst_min: future minimal intensity value
    :param float dst_max: future maximal intensity value
    :param f_low: robust cropping at low end (0.0 no cropping)
    :param f_high: robust cropping at higher end (0.999 crop one thousandths of high intensity voxels)
    :return: returns (adjusted) src_min and scale factor
    """
    # get min and max from source
    src_min = np.min(data)
    src_max = np.max(data)

    if src_min < 0.0:
        sys.exit('ERROR: Min value in input is below 0.0!')

    print("Input:    min: " + format(src_min) + "  max: " + format(src_max))

    if f_low == 0.0 and f_high == 1.0:
        return src_min, 1.0

    # compute non-zeros and total vox num
    nz = (np.abs(data) >= 1e-15).sum()
    voxnum = data.shape[0] * data.shape[1] * data.shape[2]

    # compute histogram
    histosize = 1000
    bin_size = (src_max - src_min) / histosize
    hist, bin_edges = np.histogram(data, histosize)

    # compute cummulative sum
    cs = np.concatenate(([0], np.cumsum(hist)))

    # get lower limit
    nth = int(f_low * voxnum)
    idx = np.where(cs < nth)

    if len(idx[0]) > 0:
        idx = idx[0][-1] + 1

    else:
        idx = 0

    src_min = idx * bin_size + src_min

    # print("bin min: "+format(idx)+"  nth: "+format(nth)+"  passed: "+format(cs[idx])+"\n")
    # get upper limit
    nth = voxnum - int((1.0 - f_high) * nz)
    idx = np.where(cs >= nth)

    if len(idx[0]) > 0:
        idx = idx[0][0] - 2

    else:
        print('ERROR: rescale upper bound not found')

    src_max = idx * bin_size + src_min
    # print("bin max: "+format(idx)+"  nth: "+format(nth)+"  passed: "+format(voxnum-cs[idx])+"\n")

    # scale
    if src_min == src_max:
        scale = 1.0

    else:
        scale = (dst_max - dst_min) / (src_max - src_min)

    print("rescale:  min: " + format(src_min) + "  max: " + format(src_max) + "  scale: " + format(scale))

    return src_min, scale


def scalecrop(data, dst_min, dst_max, src_min, scale):
    """
    Function to crop the intensity ranges to specific min and max values

    :param np.ndarray data: Image data (intensity values)
    :param float dst_min: future minimal intensity value
    :param float dst_max: future maximal intensity value
    :param float src_min: minimal value to consider from source (crops below)
    :param float scale: scale value by which source will be shifted
    :return: scaled Image data array
    """
    data_new = dst_min + scale * (data - src_min)

    # clip
    data_new = np.clip(data_new, dst_min, dst_max)
    print("Output:   min: " + format(data_new.min()) + "  max: " + format(data_new.max()))

    return data_new


def rescale(data, dst_min, dst_max, f_low=0.0, f_high=0.999):
    """
    Function to rescale image intensity values (0-255)

    :param np.ndarray data: Image data (intensity values)
    :param float dst_min: future minimal intensity value
    :param float dst_max: future maximal intensity value
    :param f_low: robust cropping at low end (0.0 no cropping)
    :param f_high: robust cropping at higher end (0.999 crop one thousandths of high intensity voxels)
    :return: returns scaled Image data array
    """
    src_min, scale = getscale(data, dst_min, dst_max, f_low, f_high)
    data_new = scalecrop(data, dst_min, dst_max, src_min, scale)
    return data_new


def conform(img, order=1):
    """
    Python version of mri_convert -c, which turns image intensity values into UCHAR, reslices images to standard position, fills up
    slices to standard 256x256x256 format and enforces 1 mm isotropic voxel sizes.

    Difference to mri_convert -c is that we first interpolate (float image), and then rescale to uchar. mri_convert is
    doing it the other way. However, we compute the scale factor from the input to be more similar again

    :param nibabel.MGHImage img: loaded source image
    :param int order: interpolation order (0=nearest,1=linear(default),2=quadratic,3=cubic)
    :return:nibabel.MGHImage new_img: conformed image
    """
    from nibabel.freesurfer.mghformat import MGHHeader

    cwidth = 256
    csize = 1
    h1 = MGHHeader.from_header(img.header)  # may copy some parameters if input was MGH format

    h1.set_data_shape([cwidth, cwidth, cwidth, 1])
    h1.set_zooms([csize, csize, csize])
    h1['Mdc'] = [[-1, 0, 0], [0, 0, -1], [0, 1, 0]]
    h1['fov'] = cwidth
    h1['Pxyz_c'] = img.affine.dot(np.hstack((np.array(img.shape[:3]) / 2.0, [1])))[:3]

    # from_header does not compute Pxyz_c (and probably others) when importing from nii
    # Pxyz is the center of the image in world coords

    # get scale for conversion on original input before mapping to be more similar to mri_convert
    src_min, scale = getscale(img.get_data(), 0, 255)

    mapped_data = map_image(img, h1.get_affine(), h1.get_data_shape(), order=order)
    # print("max: "+format(np.max(mapped_data)))

    if not img.get_data_dtype() == np.dtype(np.uint8):

        if np.max(mapped_data) > 255:
            mapped_data = scalecrop(mapped_data, 0, 255, src_min, scale)

    new_data = np.uint8(np.rint(mapped_data))
    new_img = nib.MGHImage(new_data, h1.get_affine(), h1)

    # make sure we store uchar
    new_img.set_data_dtype(np.uint8)

    return new_img


def is_conform(img, eps=1e-06):
    """
    Function to check if an image is already conformed or not (Dimensions: 256x256x256, Voxel size: 1x1x1, and
    LIA orientation.

    :param nibabel.MGHImage img: Loaded source image
    :param float eps: allowed deviation from zero for LIA orientation check (default 1e-06).
                      Small inaccuracies can occur through the inversion operation. Already conformed images are
                      thus sometimes not correctly recognized. The epsilon accounts for these small shifts.
    :return: True if image is already conformed, False otherwise
    """
    ishape = img.shape

    if len(ishape) > 3 and ishape[3] != 1:
        sys.exit('ERROR: Multiple input frames (' + format(img.shape[3]) + ') not supported!')

    # check dimensions
    if ishape[0] != 256 or ishape[1] != 256 or ishape[2] != 256:
        return False

    # check voxel size
    izoom = img.header.get_zooms()
    if izoom[0] != 1.0 or izoom[1] != 1.0 or izoom[2] != 1.0:
        return False

    # check orientation LIA
    iaffine = img.affine[0:3, 0:3] + [[1, 0, 0], [0, 0, -1], [0, 1, 0]]

    if np.max(np.abs(iaffine)) > 0.0 + eps:
        return False

    return True


if __name__ == "__main__":
    # Command Line options are error checking done here
    options = options_parse()

    print("Reading input: {} ...".format(options.input))
    image = nib.load(options.input)

    if len(image.shape) > 3 and image.shape[3] != 1:
        sys.exit('ERROR: Multiple input frames (' + format(image.shape[3]) + ') not supported!')

    if is_conform(image):
        sys.exit("Input " + format(options.input) + " is already conform! No output created.\n")

    new_image = conform(image, options.order)
    print ("Writing conformed image: {}".format(options.output))

    nib.save(new_image, options.output)

    sys.exit(0)


