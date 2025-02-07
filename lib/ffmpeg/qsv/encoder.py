###
### Copyright (C) 2018-2021 Intel Corporation
###
### SPDX-License-Identifier: BSD-3-Clause
###

import re
import slash

from ....lib.ffmpeg.encoderbase import BaseEncoderTest, Encoder as FFEncoder
from ....lib.ffmpeg.util import have_ffmpeg_hwaccel
from ....lib.ffmpeg.qsv.util import mapprofile, using_compatible_driver, have_encode_main10sp
from ....lib.ffmpeg.qsv.decoder import Decoder
from ....lib.common import mapRangeInt, get_media, call, exe2os

class Encoder(FFEncoder):
  hwaccel   = property(lambda s: "qsv")
  tilecols  = property(lambda s: s.ifprop("tilecols", " -tile_cols {tilecols}"))
  tilerows  = property(lambda s: s.ifprop("tilerows", " -tile_rows {tilerows}"))
  ldb       = property(lambda s: s.ifprop("ldb", " -low_delay_brc {ldb}"))

  @property
  def hwupload(self):
    return f"{super().hwupload}=extra_hw_frames=120"

  @property
  def hwdevice(self):
    return f'qsv,child_device={get_media().render_device}'

  @property
  def qp(self):
    def inner(qp):
      if self.codec in ["mpeg2"]:
        mqp = mapRangeInt(qp, [0, 100], [1, 51])
        return f" -q {mqp}"
      return f" -q {qp}"
    return self.ifprop("qp", inner)

  @property
  def quality(self):
    def inner(quality):
      if self.codec in ["jpeg"]:
        return f" -global_quality {quality}"
      return f" -preset {quality}"
    return self.ifprop("quality", inner)

  @property
  def encparams(self):
    return f"{super().encparams}{self.ldb}"

@slash.requires(*have_ffmpeg_hwaccel("qsv"))
@slash.requires(using_compatible_driver)
class EncoderTest(BaseEncoderTest):
  EncoderClass = Encoder
  DecoderClass = Decoder

  def map_profile(self):
    return mapprofile(self.codec, self.profile)

  def validate_caps(self):
    if vars(self).get("profile", None) in ["main10sp"] and not have_encode_main10sp(self.ffencoder):
      slash.skip_test(f"{self.ffencoder} main10sp not supported")

    # FIXME: this should go into BaseEncoderTest
    if self.rcmode in ["cbr", "vbr"]:
      # brframes, if specified, overrides "frames" for bitrate control modes
      self.frames = vars(self).get("brframes", self.frames)

    super().validate_caps()

  def check_metrics(self):
    # TCBRC check
    is_tcbrc = all([
      self.rcmode in ["vbr"],
      vars(self).get("lowpower", 0),
      vars(self).get("ldb", 0),
      vars(self).get("strict", 0) == -1,
    ])

    if is_tcbrc:
      output = call(
        f"{exe2os('ffprobe')} -i {self.encoder.osencoded}"
        f" -show_entries frame=pkt_size,pict_type -of compact"
      )

      actual = re.findall(r'(?<=pkt_size=).[0-9]*(?=\|pict_type=[IPB])', output)
      assert len(actual) == self.frames, "Probe failed for frame pkt_size"

      target = self.bitrate * 1000 / 8 / self.fps # target bytes per frame
      results = [int(frmsize) < target * 1.2 for frmsize in actual]
      failed = results.count(False)
      rate = failed / len(results)

      get_media()._set_test_details(**{
        "tcbrc:frame:target (bytes)" : f"{target:0.2f}",
        "tcbrc:frame:fails" : f"{failed} ({rate:0.2%})",
      })

      assert rate < 0.2, "Too many TCBRC frames exceed target frame size"

    super().check_metrics()

  def check_output(self):
    # init
    m = re.search("Initialize MFX session", self.output, re.MULTILINE)
    assert m is not None, "It appears that the QSV plugin did not load"

    # rate control mode
    if self.codec not in ["jpeg"]:
      mode = "LA" if vars(self).get("ladepth", None) is not None else self.rcmode
      m = re.search(f"RateControlMethod: {mode.upper()}", self.output, re.MULTILINE)
      assert m is not None, "Possible incorrect RC mode used"

    # lowpower
    if self.codec not in ["jpeg", "mpeg2"]:
      vdenc = "ON" if vars(self).get("lowpower", 0) else "OFF"
      m = re.search(f"VDENC: {vdenc}", self.output, re.MULTILINE)
      assert m is not None, "Possible incorrect VDENC/VME mode used"

    # fps
    if vars(self).get("fps", None) is not None:
      m = re.search(f"FrameRateExtD: 1; FrameRateExtN: {self.fps}", self.output, re.MULTILINE)
      assert m is not None, "Possible incorrect FPS used"

    # slices
    if vars(self).get("slices", None) is not None and self.codec not in ["vp9"]:
      m = re.search(f"NumSlice: {self.slices};", self.output, re.MULTILINE)
      assert m is not None, "Possible incorrect slices used"

    # ladepth
    if vars(self).get("ladepth", None) is not None:
      m = re.search(f"LookAheadDepth: {self.ladepth}", self.output, re.MULTILINE)
      assert m is not None, "The lookahead depth does not match test parameter"

    # main10sp
    if vars(self).get("profile", None) in ["main10sp"]:
      m = re.search(r"Main10sp.*: enable", self.output, re.MULTILINE)
      assert m is not None, "It appears that main10sp did not get enabled"

    # intref
    if vars(self).get("intref", None) is not None:
      patterns = [
        f"IntRefType: {self.intref['type']};",
        f"IntRefCycleSize: {self.intref['size']};",
        f"IntRefCycleDist: {self.intref['dist']}",
      ]

      for pattern in patterns:
        m = re.search(pattern, self.output, re.MULTILINE)
        assert m is not None, f"'{pattern}' missing in output"

    # Max/min qp
    if vars(self).get("rqp", None) is not None:
      patterns = [
        f"MinQPI: {self.rqp['MinQPI']};",
        f"MaxQPI: {self.rqp['MaxQPI']};",
        f"MinQPP: {self.rqp['MinQPP']};",
        f"MaxQPP: {self.rqp['MaxQPP']};",
        f"MinQPB: {self.rqp['MinQPB']};",
        f"MaxQPB: {self.rqp['MaxQPB']}",
      ]

      for pattern in patterns:
        m = re.search(pattern, self.output, re.MULTILINE)
        assert m is not None, f"'{pattern}' missing in output"

