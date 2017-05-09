import time
import unittest
from threading import Thread

from bsread.sender import Sender

import pyscan.scan
from pyscan.positioner.vector import VectorPositioner
from pyscan.scan import scan
from pyscan.scan_parameters import epics_pv, bs_property, epics_monitor, bs_monitor, scan_settings

from tests.helpers.mock_epics_dal import MockReadGroupInterface, MockWriteGroupInterface, pv_cache

# Mock the Epics DAL.
pyscan.scan.EPICS_READER = MockReadGroupInterface
pyscan.scan.EPICS_WRITER = MockWriteGroupInterface

# Load the module after the mock dal is established.
from pyscan.dal.epics_utils import action_set_epics_pv, action_restore

# Setup mock values
from tests.helpers.mock_epics_dal import cached_initial_values
cached_initial_values["PYSCAN:TEST:VALID1"] = 10
cached_initial_values["PYSCAN:TEST:OBS1"] = 1

bs_sending = True


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

    def test_monitors(self):
        # TODO: Test if the monitors belong to the same output as the values.
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

        result = scan(positioner=positioner,
                      writables=writables,
                      readables=readables,
                      initialization=initialization,
                      finalization=finalization,
                      settings=scan_settings(measurement_interval=0.25,
                                             n_measurements=1))

        self.assertEqual(pv_cache["PYSCAN:TEST:MOTOR1:SET"][0].value, -11,
                         "Finalization did not restore original value.")
        self.assertEqual(pv_cache["PYSCAN:TEST:MOTOR2:SET"][0].value, -22,
                         "Finalization did not restore original value.")

        self.assertEqual(result[0][0], -33, "Initialization action did not work.")

    def test_mixed_sources(self):
        positions = [[1, 1], [2, 2], [3, 3], [4, 4]]
        positioner = VectorPositioner(positions)

        writables = [epics_pv("PYSCAN:TEST:MOTOR1:SET", "PYSCAN:TEST:MOTOR1:GET"),
                     epics_pv("PYSCAN:TEST:MOTOR2:SET", "PYSCAN:TEST:MOTOR2:GET")]

        readables = [bs_property("CAMERA1:X"),
                     bs_property("CAMERA1:Y"),
                     epics_pv("PYSCAN:TEST:OBS1")]

        monitors = [epics_monitor("PYSCAN:TEST:VALID1", 10),
                    bs_monitor("CAMERA1:VALID", 10)]

        initialization = [action_set_epics_pv("PYSCAN:TEST:PRE1:SET", 1, "PYSCAN:TEST:PRE1:GET")]

        finalization = [action_set_epics_pv("PYSCAN:TEST:PRE1:SET", 0, "PYSCAN:TEST:PRE1:GET"),
                        action_restore(writables)]

        result = scan(positioner=positioner,
                      writables=writables,
                      readables=readables,
                      monitors=monitors,
                      initialization=initialization,
                      finalization=finalization,
                      settings=scan_settings(measurement_interval=0.25,
                                             n_measurements=1))

        self.assertEqual(len(result), len(positions), "Not the expected number of results.")

        # The first 2 attributes are from bs_read, they should be equal to the pulse ID processed.
        self.assertTrue(all(x[0] == x[1] and x[2] == 1 for x in result), "The result is wrong.")
