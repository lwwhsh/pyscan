from pyscan.utils import convert_to_list


class FunctionProxy(object):
    """
    Provide an interface for using external methods as DAL.
    """
    def __init__(self, functions):
        """
        Initialize the function dal.
        :param functions: List (or single item) of FUNCTION_VALUE type.
        """
        self.functions = convert_to_list(functions)

    def read(self):
        """
        Read the results from all the provided functions.
        :return: Read results.
        """
        results = []
        for func in self.functions:
            results.append(func.call_function())

        return results

    def write(self, values):
        """
        Write the values to the provided functions.
        :param values: Values to write.
        """

        values = convert_to_list(values)
        for func, value in zip(self.functions, values):
            func.call_function(value)
