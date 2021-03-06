import sys
import time
import unittest
from collections import OrderedDict
from threading import Thread

from bsread.sender import Sender

from pyscan import SimpleDataProcessor, config, StaticPositioner, scan_settings, function_value
from pyscan.config import max_time_tolerance
from pyscan.positioner.time import TimePositioner
from pyscan.utils import DictionaryDataProcessor
from tests.helpers.mock_epics_dal import MockReadGroupInterface, MockWriteGroupInterface, cached_initial_values

# BEGIN EPICS MOCK.

scan_module = sys.modules["pyscan.scan"]
utils_module = sys.modules["pyscan.scan_actions"]

utils_module.EPICS_READER = MockReadGroupInterface
utils_module.EPICS_WRITER = MockWriteGroupInterface
scan_module.EPICS_READER = MockReadGroupInterface
scan_module.EPICS_WRITER = MockWriteGroupInterface

# Setup mock values
cached_initial_values["PYSCAN:TEST:VALID1"] = 10
cached_initial_values["PYSCAN:TEST:OBS1"] = 1

# END OF MOCK.

from pyscan.scan import scan
from pyscan.positioner.vector import VectorPositioner
from pyscan.scan_parameters import epics_pv, bs_property, epics_condition, bs_condition, scan_settings
from pyscan.scan_actions import action_set_epics_pv, action_restore
from tests.helpers.mock_epics_dal import pv_cache


def start_sender():
    # Start a mock sender stream.
    generator = Sender(block=False)
    generator.add_channel('CAMERA1:X', lambda x: x, metadata={'type': 'int32'})
    generator.add_channel('CAMERA1:Y', lambda x: x, metadata={'type': 'int32'})
    generator.add_channel('CAMERA1:VALID', lambda x: 10, metadata={'type': 'int32'})

    generator.open()
    while bs_sending:
        generator.send()
        time.sleep(0.05)

    generator.close()


bs_sending = True


class ScanTests(unittest.TestCase):
    def setUp(self):
        global bs_sending
        bs_sending = True

        self.sender_thread = Thread(target=start_sender)
        self.sender_thread.daemon = True
        self.sender_thread.start()

    def tearDown(self):
        global bs_sending
        bs_sending = False

        self.sender_thread.join()

    def test_conditions(self):
        # TODO: Test if the conditions belong to the same output as the values.
        pass

    def test_actions(self):
        positions = [[1, 1], [2, 2]]
        positioner = VectorPositioner(positions)

        writables = [epics_pv("PYSCAN:TEST:MOTOR1:SET", "PYSCAN:TEST:MOTOR1:GET"),
                     epics_pv("PYSCAN:TEST:MOTOR2:SET", "PYSCAN:TEST:MOTOR2:GET")]

        readables = [epics_pv("PYSCAN:TEST:OBS1")]

        # MOTOR1 initial values should be -11, MOTOR2 -22.
        cached_initial_values["PYSCAN:TEST:MOTOR1:SET"] = -11
        cached_initial_values["PYSCAN:TEST:MOTOR2:SET"] = -22
        initialization = [action_set_epics_pv("PYSCAN:TEST:OBS1", -33)]
        finalization = [action_restore(writables)]

        result = scan(positioner=positioner, readables=readables, writables=writables, initialization=initialization,
                      finalization=finalization, settings=scan_settings(measurement_interval=0.25,
                                                                        n_measurements=1))

        self.assertEqual(pv_cache["PYSCAN:TEST:MOTOR1:SET"][0].value, -11,
                         "Finalization did not restore original value.")
        self.assertEqual(pv_cache["PYSCAN:TEST:MOTOR2:SET"][0].value, -22,
                         "Finalization did not restore original value.")

        self.assertEqual(result[0][0], -33, "Initialization action did not work.")

    def test_mixed_sources(self):
        config.bs_connection_mode = "pull"

        positions = [[1, 1], [2, 2], [3, 3], [4, 4]]
        positioner = VectorPositioner(positions)

        writables = [epics_pv("PYSCAN:TEST:MOTOR1:SET", "PYSCAN:TEST:MOTOR1:GET"),
                     epics_pv("PYSCAN:TEST:MOTOR2:SET", "PYSCAN:TEST:MOTOR2:GET")]

        readables = [bs_property("CAMERA1:X"),
                     bs_property("CAMERA1:Y"),
                     epics_pv("PYSCAN:TEST:OBS1")]

        conditions = [epics_condition("PYSCAN:TEST:VALID1", 10),
                    bs_condition("CAMERA1:VALID", 10)]

        initialization = [action_set_epics_pv("PYSCAN:TEST:PRE1:SET", 1, "PYSCAN:TEST:PRE1:GET")]

        finalization = [action_set_epics_pv("PYSCAN:TEST:PRE1:SET", 0, "PYSCAN:TEST:PRE1:GET"),
                        action_restore(writables)]

        result = scan(positioner=positioner, readables=readables, writables=writables, conditions=conditions,
                      initialization=initialization, finalization=finalization,
                      settings=scan_settings(measurement_interval=0.25,
                                             n_measurements=1))

        self.assertEqual(len(result), len(positions), "Not the expected number of results.")

        # The first 2 attributes are from bs_read, they should be equal to the pulse ID processed.
        self.assertTrue(all(x[0] == x[1] and x[2] == 1 for x in result), "The result is wrong.")

    def test_progress_monitor(self):

        current_index = []
        total_positions = 0
        current_percentage = []

        def progress(current_position, max_position):
            current_index.append(current_position)
            current_percentage.append(100 * (current_position / max_position))

            nonlocal total_positions
            total_positions = max_position

        positions = [1, 2, 3, 4, 5]
        positioner = VectorPositioner(positions)
        writables = epics_pv("PYSCAN:TEST:MOTOR1:SET", "PYSCAN:TEST:MOTOR1:GET")
        readables = epics_pv("PYSCAN:TEST:OBS1")
        settings = scan_settings(progress_callback=progress)

        scan(positioner, readables, writables, settings=settings)

        self.assertEqual(len(positions) + 1, len(current_index), "The number of reported positions is wrong.")
        self.assertEqual(total_positions, 5, "The number of total positions is wrong.")
        self.assertEqual(current_index, [0, 1, 2, 3, 4, 5], "The reported percentage is wrong.")
        self.assertEqual(current_percentage, [0, 20, 40, 60, 80, 100], "The reported percentage is wrong.")

    def test_time_scan(self):
        n_intervals = 10
        time_interval = 0.1

        positioner = TimePositioner(time_interval, n_intervals)
        readables = epics_pv("PYSCAN:TEST:OBS1")
        data_processor = SimpleDataProcessor()

        scan(positioner, readables, data_processor=data_processor)
        result = data_processor.get_data()

        self.assertEqual(len(result), n_intervals)

        acquisition_times = data_processor.get_positions()

        for index in range(n_intervals - 1):
            time_difference = acquisition_times[index + 1] - acquisition_times[index]
            self.assertTrue(abs(time_difference - time_interval) < max_time_tolerance,
                            "The acquisition time difference is larger than the minimum tolerance.")

    def test_convert_readables(self):
        config.bs_connection_mode = "pull"

        positions = [[0, 10], [1, 11], [2, 12], [2, 13]]
        positioner = VectorPositioner(positions)

        readables = [bs_property("CAMERA1:X"),
                     "bs://CAMERA1:X",
                     "BS://CAMERA1:X",
                     epics_pv("PYSCAN:TEST:OBS1"),
                     "PYSCAN:TEST:OBS1",
                     "ca://PYSCAN:TEST:OBS1",
                     "CA://PYSCAN:TEST:OBS1"]

        writables = ["ca://PYSCAN:TEST:MOTOR1:SET",
                     "PYSCAN:TEST:MOTOR2:SET"]

        def collect_positions():
            actual_positions.append([pv_cache["PYSCAN:TEST:MOTOR1:SET"][0].value,
                                     pv_cache["PYSCAN:TEST:MOTOR2:SET"][0].value])

        actual_positions = []

        result = scan(positioner=positioner, readables=readables, writables=writables, after_read=collect_positions)
        for index in range(len(positions)):
            self.assertTrue(result[index][0] == result[index][1] == result[index][2],
                            "Not all acquisitions are equal.")
            self.assertTrue(result[index][3] == result[index][4] == result[index][5],
                            "Not all acquisitions are equal.")

        self.assertEqual(positions, actual_positions, "Does not work for writables.")

    def test_bs_read_filter(self):
        config.bs_connection_mode = "pull"

        n_images = 10
        positioner = StaticPositioner(n_images)
        readables = ["bs://CAMERA1:X"]

        # Count how many messages passed.
        def mock_filter(message):
            if message:
                nonlocal filter_pass
                filter_pass += 1
            return True

        filter_pass = 0

        settings = scan_settings(bs_read_filter=mock_filter)

        # settings = scan_settings(bs_read_filter=mock_filter)
        result = scan(positioner=positioner, readables=readables, settings=settings)

        # The length should still be the same - the filter just throws away messages we do not want.
        self.assertEqual(len(result), n_images)

        self.assertTrue(filter_pass >= n_images, "The filter passed less then the received messages.")
        # TODO: Some more sophisticated filter tests.

    def test_bs_read_default_values(self):
        # DO NOT INCLUDE IN README - default.
        config.bs_connection_mode = "pull"
        config.bs_default_missing_property_value = Exception

        n_images = 10
        # Get 10 images.
        positioner = StaticPositioner(n_images)
        # Get CAMERA1 X, Y property, and 2 invalid properites with default values.
        default_invalid2_value = -999
        readables = ["bs://CAMERA1:X", "bs://CAMERA1:Y",
                     bs_property("invalid", None), bs_property("invalid2", default_invalid2_value)]
        result = scan(positioner, readables)

        self.assertEqual(len(result), n_images)
        self.assertTrue(all(x[2] is None for x in result), "Default property value not as expected.")
        self.assertTrue(all(x[3] == default_invalid2_value for x in result), "Default property value not as expected.")

        # A missing bs_property without default value should rise an exception.
        readables = ["bs://CAMERA1:X", "bs://CAMERA1:Y", bs_property("invalid")]

        with self.assertRaisesRegex(Exception, "Property 'invalid' missing in bs stream."):
            scan(positioner, readables)

    def test_bs_read_config_default_value(self):
        # DO NOT INCLUDE IN README - default.
        config.bs_connection_mode = "pull"

        # Get 10 images.
        n_images = 3
        positioner = StaticPositioner(n_images)
        readables = ["bs://CAMERA1:INVALID"]

        with self.assertRaisesRegex(Exception, "Property 'CAMERA1:INVALID' missing in bs stream."):
            scan(positioner, readables)

        default_value = 42
        config.bs_default_missing_property_value = default_value
        result = scan(positioner, readables)

        self.assertEqual(len(result), n_images)
        self.assertTrue(all(x[0] == default_value for x in result), "Default value from properties not working.")

    def test_readables_function_value(self):
        # Initialize the function counter to prevent test interferences.
        function_value.function_count = 0

        def simple_counter():
            nonlocal counter
            counter += 1
            return counter

        counter = 0

        n_images = 2
        readables = [simple_counter, simple_counter]
        positioner = StaticPositioner(n_images)

        result = scan(positioner, readables)
        self.assertEqual(result, [[1, 2], [3, 4]], "Result not as expected")

        def double_counter():
            nonlocal counter
            counter += 1
            return [counter, counter]

        counter = 0

        readables = [function_value(double_counter, "double_trouble"), simple_counter, simple_counter]
        data_processor = DictionaryDataProcessor(readables)
        result = scan(positioner, readables, data_processor=data_processor)

        expected_result = [OrderedDict([('double_trouble', [1, 1]), ('function_2', 2), ('function_3', 3)]),
                           OrderedDict([('double_trouble', [4, 4]), ('function_2', 5), ('function_3', 6)])]

        self.assertEqual(result, expected_result, "Result not as expected.")

        readables = [simple_counter, "ca://PYSCAN:TEST:OBS1", double_counter, "ca://PYSCAN:TEST:OBS2"]
        data_processor = DictionaryDataProcessor(readables)

        result = scan(positioner, readables, data_processor=data_processor)
        expected_result = [OrderedDict([('function_6', 7),
                                        ('PYSCAN:TEST:OBS1', 1),
                                        ('function_7', [8, 8]),
                                        ('PYSCAN:TEST:OBS2', 'PYSCAN:TEST:OBS2')]),

                           OrderedDict([('function_6', 9),
                                        ('PYSCAN:TEST:OBS1', 1),
                                        ('function_7', [10, 10]),
                                        ('PYSCAN:TEST:OBS2', 'PYSCAN:TEST:OBS2')])]

        self.assertEqual(result, expected_result, "Result not as expected.")

    def test_writeable_function_value(self):
        def nop():
            return 0

        def write(position):
            positions.append(position)
        positions = []

        # Get 10 images.
        readables = [nop]
        expected_positions = [1, 2, 3, 4, 5]
        positioner = VectorPositioner(expected_positions)
        writables = write

        scan(positioner, readables=readables, writables=writables)
        self.assertEqual(positions, expected_positions, "Expected positions not equal.")

        def write2(position):
            positions2.append(position)
        positions2 = []

        positions.clear()
        expected_positions = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
        writables = ["something1", write, "something2", write2]
        positioner = VectorPositioner(expected_positions)

        scan(positioner, readables=readables, writables=writables)

        self.assertEqual(positions, [x[1] for x in expected_positions], "Values not as expected.")
        self.assertEqual(positions2, [x[3] for x in expected_positions], "Values not as expected")

    def test_condition_function_value(self):

        def pass_condition():
            return True

        n_images = 2
        readables = ["something1"]
        positioner = StaticPositioner(n_images)
        conditions = pass_condition
        scan(positioner, readables, conditions=conditions)

        def fail_condition():
            return False

        conditions = fail_condition

        with self.assertRaisesRegex(ValueError, "Function condition function_condition_"):
            scan(positioner, readables, conditions=conditions)

    def test_before_after_move_executor(self):

        def void_read():
            return 1

        def void_write(position):
            positions.append(position)
        positions = []

        def before_move(position):
            self.assertTrue(position not in positions, "Positions already visited.")

        def after_move(position):
            self.assertTrue(position in positions, "Position not yet visited.")

        positioner = VectorPositioner([1, 2, 3, 4, 5, 6])

        scan(readables=void_read, writables=void_write, positioner=positioner,
             before_move=before_move, after_move=after_move)