
class NImagePositioner(object):
    def __init__(self, n_images):
        """
        Acquire N consequtive images.
        :param n_images: Number of images to acquire.
        """
        self.n_images = n_images

    def get_generator(self):
        for index in range(self.n_images):
            yield index