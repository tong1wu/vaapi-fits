###
### Copyright (C) 2021 Intel Corporation
###
### SPDX-License-Identifier: BSD-3-Clause
###

from ...lib.common import memoize, try_call, call, exe2os

@memoize
def have_gst():
  return try_call(f"which {exe2os('gst-launch-1.0')}") and try_call(f"which {exe2os('gst-inspect-1.0')}")

@memoize
def have_gst_element(element):
  result = try_call(f"{exe2os('gst-inspect-1.0')}"
                    " {}".format(element))
  return result, element

def gst_discover(filename):
  return call(f"{exe2os('gst-discoverer-1.0')}"
              " {}".format(filename))
