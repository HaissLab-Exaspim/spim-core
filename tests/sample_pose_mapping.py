#!/usr/bin/env python3

import pytest
from math import isclose
from tigerasi.sim_tiger_controller import SimTigerController
from spim_core.devices.tiger_components import SamplePose
#import logging
#
## Send log messages to stdout so we can see every outgoing/incoming tiger msg.
#logger = logging.getLogger()
#logger.setLevel(logging.DEBUG)
#logger.addHandler(logging.StreamHandler())
#logger.handlers[-1].setFormatter(
#   logging.Formatter(fmt='%(asctime)s:%(levelname)s: %(message)s'))



def test_move_x_and_y():
    axis_map = {'X': 'Y', 'Y': '-Z', 'Z': 'X'}
    box = SimTigerController()
    sample_pose = SamplePose(box, axis_map)

    move = {'x':10, 'y': 50, 'z': 0}
    sample_pose.zero_in_place()
    # move_absolute will invoke self._sample_to_tiger
    sample_pose.move_absolute(**move)
    # get_position will invoke self._tiger_to_sample
    real_move = sample_pose.get_position() # returns dict with x, y, z keys.
    # Compare dictionaries.
    val = [isclose(move[x], real_move[x])
           for x in set(move.keys()) | set(real_move.keys())]
    assert all(val)
