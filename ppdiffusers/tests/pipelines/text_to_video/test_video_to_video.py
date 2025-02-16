# Copyright (c) 2023 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import random
import unittest

import numpy as np
import paddle
from paddlenlp.transformers import CLIPTextConfig, CLIPTextModel, CLIPTokenizer

from ppdiffusers import (
    AutoencoderKL,
    DDIMScheduler,
    UNet3DConditionModel,
    VideoToVideoSDPipeline,
)
from ppdiffusers.utils import floats_tensor, is_ppxformers_available
from ppdiffusers.utils.testing_utils import enable_full_determinism, slow

from ..pipeline_params import (
    TEXT_GUIDED_IMAGE_VARIATION_BATCH_PARAMS,
    TEXT_GUIDED_IMAGE_VARIATION_PARAMS,
)
from ..test_pipelines_common import PipelineTesterMixin

enable_full_determinism()


def to_np(tensor):
    if isinstance(tensor, paddle.Tensor):
        tensor = tensor.detach().cpu().numpy()

    if isinstance(tensor, (list, tuple)):
        tensor = np.array(tensor)

    return tensor


class VideoToVideoSDPipelineFastTests(PipelineTesterMixin, unittest.TestCase):
    pipeline_class = VideoToVideoSDPipeline
    params = TEXT_GUIDED_IMAGE_VARIATION_PARAMS.union({"video"}) - {"image", "width", "height"}
    batch_params = TEXT_GUIDED_IMAGE_VARIATION_BATCH_PARAMS.union({"video"}) - {"image"}
    required_optional_params = PipelineTesterMixin.required_optional_params - {"latents"}
    test_attention_slicing = False
    required_optional_params = frozenset(
        ["num_inference_steps", "generator", "latents", "return_dict", "callback", "callback_steps"]
    )

    def get_dummy_components(self):
        paddle.seed(seed=0)
        unet = UNet3DConditionModel(
            block_out_channels=(32, 64, 64, 64),
            layers_per_block=2,
            sample_size=32,
            in_channels=4,
            out_channels=4,
            down_block_types=("CrossAttnDownBlock3D", "CrossAttnDownBlock3D", "CrossAttnDownBlock3D", "DownBlock3D"),
            up_block_types=("UpBlock3D", "CrossAttnUpBlock3D", "CrossAttnUpBlock3D", "CrossAttnUpBlock3D"),
            cross_attention_dim=32,
            attention_head_dim=4,
        )
        scheduler = DDIMScheduler(
            beta_start=0.00085,
            beta_end=0.012,
            beta_schedule="scaled_linear",
            clip_sample=False,
            set_alpha_to_one=False,
        )
        paddle.seed(seed=0)
        vae = AutoencoderKL(
            block_out_channels=[32, 64],
            in_channels=3,
            out_channels=3,
            down_block_types=["DownEncoderBlock2D", "DownEncoderBlock2D"],
            up_block_types=["UpDecoderBlock2D", "UpDecoderBlock2D"],
            latent_channels=4,
            sample_size=128,
        )
        paddle.seed(seed=0)
        text_encoder_config = CLIPTextConfig(
            bos_token_id=0,
            eos_token_id=2,
            hidden_size=32,
            intermediate_size=37,
            layer_norm_eps=1e-05,
            num_attention_heads=4,
            num_hidden_layers=5,
            pad_token_id=1,
            vocab_size=1000,
            hidden_act="gelu",
            projection_dim=512,
        )
        text_encoder = CLIPTextModel(text_encoder_config)
        tokenizer = CLIPTokenizer.from_pretrained("hf-internal-testing/tiny-random-clip")
        components = {
            "unet": unet,
            "scheduler": scheduler,
            "vae": vae,
            "text_encoder": text_encoder,
            "tokenizer": tokenizer,
        }
        return components

    def get_dummy_inputs(self, seed=0):
        video = floats_tensor((1, 3, 3, 32, 32), rng=random.Random(seed))
        generator = paddle.Generator().manual_seed(seed)
        inputs = {
            "prompt": "A painting of a squirrel eating a burger",
            "video": video,
            "generator": generator,
            "num_inference_steps": 2,
            "guidance_scale": 6.0,
            "output_type": "pt",
        }
        return inputs

    def test_text_to_video_default_case(self):
        components = self.get_dummy_components()
        sd_pipe = VideoToVideoSDPipeline(**components)
        sd_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        inputs["output_type"] = "np"
        frames = sd_pipe(**inputs).frames
        image_slice = frames[0][-3:, -3:, (-1)]
        assert frames[0].shape == (32, 32, 3)
        expected_slice = np.array([75, 134, 97, 103, 199, 117, 146, 174, 122])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.01

    @unittest.skipIf(
        not is_ppxformers_available(), reason="XFormers attention is only available with CUDA and `xformers` installed"
    )
    def test_xformers_attention_forwardGenerator_pass(self):
        self._test_xformers_attention_forwardGenerator_pass(
            test_max_difference=False, test_mean_pixel_difference=False, expected_max_diff=0.05
        )

    @unittest.skip(reason="Batching needs to be properly figured out first for this pipeline.")
    def test_inference_batch_consistent(self):
        pass

    @unittest.skip(reason="Batching needs to be properly figured out first for this pipeline.")
    def test_inference_batch_single_identical(self):
        pass

    @unittest.skip(reason="`num_images_per_prompt` argument is not supported for this pipeline.")
    def test_num_images_per_prompt(self):
        pass

    def test_save_load_optional_components(self):
        pass

    def test_save_load_local(self):
        pass

    def test_progress_bar(self):
        return super().test_progress_bar()

    def test_dict_tuple_outputs_equivalent(self):
        components = self.get_dummy_components()
        pipe = self.pipeline_class(**components)
        pipe.set_progress_bar_config(disable=None)

        output = pipe(**self.get_dummy_inputs())[0]
        output_tuple = pipe(**self.get_dummy_inputs(), return_dict=False)[0]
        mean_diff = np.abs(to_np(output) - to_np(output_tuple)).mean()
        self.assertLess(mean_diff, 0.5)


@slow
class VideoToVideoSDPipelineSlowTests(unittest.TestCase):
    def test_two_step_model(self):
        pipe = VideoToVideoSDPipeline.from_pretrained("cerspense/zeroscope_v2_XL", torch_dtype="float16")
        generator = paddle.Generator().manual_seed(0)
        video = paddle.randn(shape=(1, 10, 3, 1024, 576), generator=generator)
        prompt = "Spiderman is surfing"
        video_frames = pipe(prompt, video=video, generator=generator, num_inference_steps=3, output_type="pt").frames
        expected_array = np.array([-1.0458984, -1.1279297, -0.9663086, -0.91503906, -0.75097656])
        assert np.abs(video_frames.cpu().numpy()[(0), (0), (0), (0), -5:] - expected_array).sum() < 0.01
