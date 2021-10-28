# Copyright 2019 The TensorFlow Authors, Pavel Yakubovskiy, Björn Barz. All Rights Reserved.
#
# Modifications copyright 2021 AI Singapore
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
# ==============================================================================
# Contains definitions for EfficientNet model.
#
# [1] Mingxing Tan, Quoc V. Le
#   EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks.
#   ICML'19, https://arxiv.org/abs/1905.11946
#
# Code of this model implementation is mostly written by
# Björn Barz ([@Callidior](https://github.com/Callidior))

"""
EfficientNet parameters and constants
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import math
import string
import collections
from typing import Any, Dict, Callable, List, Tuple, Union

from six.moves import xrange
import tensorflow as tf
from tensorflow.python.keras.applications.imagenet_utils import obtain_input_shape
from tensorflow.keras.applications.imagenet_utils import (
    preprocess_input as _preprocess_input,
)

from peekingduck.pipeline.nodes.model.efficientdet_d04.efficientdet_files.utils.submodule import (
    get_submodules_from_kwargs,
)


BACKEND = None
LAYERS = None
MODELS = None
KERAS_UTILS = None


BASE_WEIGHTS_PATH = (
    "https://github.com/Callidior/keras-applications/releases/download/efficientnet/"
)

# fmt: off
WEIGHTS_HASHES = {
    "efficientnet-b0": (
        "163292582f1c6eaca8e7dc7b51b01c61"
        "5b0dbc0039699b4dcd0b975cc21533dc",
        "c1421ad80a9fc67c2cc4000f666aa507"
        "89ce39eedb4e06d531b0c593890ccff3",
    ),
    "efficientnet-b1": (
        "d0a71ddf51ef7a0ca425bab32b7fa7f1"
        "6043ee598ecee73fc674d9560c8f09b0",
        "75de265d03ac52fa74f2f510455ba64f"
        "9c7c5fd96dc923cd4bfefa3d680c4b68",
    ),
    "efficientnet-b2": (
        "bb5451507a6418a574534aa76a91b106"
        "f6b605f3b5dde0b21055694319853086",
        "433b60584fafba1ea3de07443b74cfd3"
        "2ce004a012020b07ef69e22ba8669333",
    ),
    "efficientnet-b3": (
        "03f1fba367f070bd2545f081cfa7f3e7"
        "6f5e1aa3b6f4db700f00552901e75ab9",
        "c5d42eb6cfae8567b418ad3845cfd63a"
        "a48b87f1bd5df8658a49375a9f3135c7",
    ),
    "efficientnet-b4": (
        "98852de93f74d9833c8640474b2c698d"
        "b45ec60690c75b3bacb1845e907bf94f",
        "7942c1407ff1feb34113995864970cd4"
        "d9d91ea64877e8d9c38b6c1e0767c411",
    ),
    "efficientnet-b5": (
        "30172f1d45f9b8a41352d4219bf930ee"
        "3339025fd26ab314a817ba8918fefc7d",
        "9d197bc2bfe29165c10a2af8c2ebc675"
        "07f5d70456f09e584c71b822941b1952",
    ),
    "efficientnet-b6": (
        "f5270466747753485a082092ac9939ca"
        "a546eb3f09edca6d6fff842cad938720",
        "1d0923bb038f2f8060faaf0a0449db4b"
        "96549a881747b7c7678724ac79f427ed",
    ),
    "efficientnet-b7": (
        "876a41319980638fa597acbbf956a82d"
        "10819531ff2dcb1a52277f10c7aefa1a",
        "60b56ff3a8daccc8d96edfd40b204c11"
        "3e51748da657afd58034d54d3cec2bac",
    ),
}
# fmt: on

BlockArgs = collections.namedtuple(
    "BlockArgs",
    [
        "kernel_size",
        "num_repeat",
        "input_filters",
        "output_filters",
        "expand_ratio",
        "id_skip",
        "strides",
        "se_ratio",
    ],
)
# defaults will be a public argument for namedtuple in Python 3.7
# https://docs.python.org/3/library/collections.html#collections.namedtuple
# mypy: ignore-errors
BlockArgs.__new__.__defaults__ = (None,) * len(BlockArgs._fields)  # type: ignore

DEFAULT_BLOCKS_ARGS = (
    BlockArgs(
        kernel_size=3,
        num_repeat=1,
        input_filters=32,
        output_filters=16,
        expand_ratio=1,
        id_skip=True,
        strides=[1, 1],
        se_ratio=0.25,
    ),
    BlockArgs(
        kernel_size=3,
        num_repeat=2,
        input_filters=16,
        output_filters=24,
        expand_ratio=6,
        id_skip=True,
        strides=[2, 2],
        se_ratio=0.25,
    ),
    BlockArgs(
        kernel_size=5,
        num_repeat=2,
        input_filters=24,
        output_filters=40,
        expand_ratio=6,
        id_skip=True,
        strides=[2, 2],
        se_ratio=0.25,
    ),
    BlockArgs(
        kernel_size=3,
        num_repeat=3,
        input_filters=40,
        output_filters=80,
        expand_ratio=6,
        id_skip=True,
        strides=[2, 2],
        se_ratio=0.25,
    ),
    BlockArgs(
        kernel_size=5,
        num_repeat=3,
        input_filters=80,
        output_filters=112,
        expand_ratio=6,
        id_skip=True,
        strides=[1, 1],
        se_ratio=0.25,
    ),
    BlockArgs(
        kernel_size=5,
        num_repeat=4,
        input_filters=112,
        output_filters=192,
        expand_ratio=6,
        id_skip=True,
        strides=[2, 2],
        se_ratio=0.25,
    ),
    BlockArgs(
        kernel_size=3,
        num_repeat=1,
        input_filters=192,
        output_filters=320,
        expand_ratio=6,
        id_skip=True,
        strides=[1, 1],
        se_ratio=0.25,
    ),
)

CONV_KERNEL_INITIALIZER = {
    "class_name": "VarianceScaling",
    "config": {
        "scale": 2.0,
        "mode": "fan_out",
        # EfficientNet actually uses an untruncated normal distribution for
        # initializing conv layers, but keras.initializers.VarianceScaling use
        # a truncated distribution.
        # We decided against a custom initializer for better serializability.
        "distribution": "normal",
    },
}

DENSE_KERNEL_INITIALIZER = {
    "class_name": "VarianceScaling",
    "config": {"scale": 1.0 / 3.0, "mode": "fan_out", "distribution": "uniform"},
}


def preprocess_input(model_input: tf.Tensor, **kwargs: Dict[str, Any]) -> tf.Tensor:
    """Preprocesses model input"""
    kwargs = {
        k: v for k, v in kwargs.items() if k in ["backend", "layers", "models", "utils"]
    }
    return _preprocess_input(model_input, mode="torch", **kwargs)


def get_swish(**kwargs: Dict[str, Any]) -> Callable:
    """Swish activation function: x * sigmoid(x).
    Reference: [Searching for Activation Functions](https://arxiv.org/abs/1710.05941)
    """
    backend, _, _, _ = get_submodules_from_kwargs(kwargs)

    def swish(swish_x: tf.Tensor) -> tf.Tensor:

        if backend.backend() == "tensorflow":
            try:
                # The native TF implementation has a more
                # memory-efficient gradient implementation
                return backend.tf.nn.swish(swish_x)
            except AttributeError:
                pass

        return swish_x * backend.sigmoid(swish_x)

    return swish


def get_dropout(**kwargs: Union[None, Dict[str, Any]]) -> Any:
    """Wrapper over custom dropout. Fix problem of ``None`` shape for tf.keras.
    It is not possible to define FixedDropout class as global object,
    because we do not have modules for inheritance at first time.

    Issue:
        https://github.com/tensorflow/tensorflow/issues/30946
    """
    backend, layers, _, _ = get_submodules_from_kwargs(kwargs)

    class FixedDropout(layers.Dropout):  # pylint: disable=too-few-public-methods
        """Fixed Dropout Class"""

        def _get_noise_shape(self, inputs: tf.Tensor) -> Union[None, Tuple[Any, ...]]:
            if self.noise_shape is None:
                return self.noise_shape

            symbolic_shape = backend.shape(inputs)
            noise_shape = [
                symbolic_shape[axis] if shape is None else shape
                for axis, shape in enumerate(self.noise_shape)
            ]
            return tuple(noise_shape)

    return FixedDropout


def round_filters(filters: float, width_coefficient: float, depth_divisor: int) -> int:
    """Round number of filters based on width multiplier."""

    filters *= width_coefficient
    new_filters = int(filters + depth_divisor / 2) // depth_divisor * depth_divisor
    new_filters = max(depth_divisor, new_filters)
    # Make sure that round down does not go down by more than 10%.
    if new_filters < 0.9 * filters:
        new_filters += depth_divisor
    return int(new_filters)


def round_repeats(repeats: int, depth_coefficient: float) -> int:
    """Round number of repeats based on depth multiplier."""

    return int(math.ceil(depth_coefficient * repeats))


def mb_conv_block(
    inputs: tf.Tensor,  # type:ignore
    block_args,
    activation: Callable,
    drop_rate: float = None,
    prefix: str = "",
) -> tf.Tensor:
    """Mobile Inverted Residual Bottleneck."""

    has_se = (block_args.se_ratio is not None) and (0 < block_args.se_ratio <= 1)
    bn_axis = 3 if BACKEND.image_data_format() == "channels_last" else 1

    # workaround over non working dropout with None in noise_shape in tf.keras
    Dropout = get_dropout(
        backend=BACKEND, layers=LAYERS, models=MODELS, utils=KERAS_UTILS
    )

    # Expansion phase
    filters = block_args.input_filters * block_args.expand_ratio
    if block_args.expand_ratio != 1:
        x_in = LAYERS.Conv2D(
            filters,
            1,
            padding="same",
            use_bias=False,
            kernel_initializer=CONV_KERNEL_INITIALIZER,
            name=prefix + "expand_conv",
        )(inputs)
        x_in = LAYERS.BatchNormalization(axis=bn_axis, name=prefix + "expand_bn")(x_in)
        x_in = LAYERS.Activation(activation, name=prefix + "expand_activation")(x_in)
    else:
        x_in = inputs

    # Depthwise Convolution
    x_in = LAYERS.DepthwiseConv2D(
        block_args.kernel_size,
        strides=block_args.strides,
        padding="same",
        use_bias=False,
        depthwise_initializer=CONV_KERNEL_INITIALIZER,
        name=prefix + "dwconv",
    )(x_in)
    x_in = LAYERS.BatchNormalization(axis=bn_axis, name=prefix + "bn")(x_in)
    x_in = LAYERS.Activation(activation, name=prefix + "activation")(x_in)

    # Squeeze and Excitation phase
    if has_se:
        num_reduced_filters = max(
            1, int(block_args.input_filters * block_args.se_ratio)
        )
        se_tensor = LAYERS.GlobalAveragePooling2D(name=prefix + "se_squeeze")(x_in)

        target_shape = (
            (1, 1, filters)
            if BACKEND.image_data_format() == "channels_last"
            else (filters, 1, 1)
        )
        se_tensor = LAYERS.Reshape(target_shape, name=prefix + "se_reshape")(se_tensor)
        se_tensor = LAYERS.Conv2D(
            num_reduced_filters,
            1,
            activation=activation,
            padding="same",
            use_bias=True,
            kernel_initializer=CONV_KERNEL_INITIALIZER,
            name=prefix + "se_reduce",
        )(se_tensor)
        se_tensor = LAYERS.Conv2D(
            filters,
            1,
            activation="sigmoid",
            padding="same",
            use_bias=True,
            kernel_initializer=CONV_KERNEL_INITIALIZER,
            name=prefix + "se_expand",
        )(se_tensor)
        if BACKEND.backend() == "theano":
            # For the Theano backend, we have to explicitly make
            # the excitation weights broadcastable.
            pattern = (
                [True, True, True, False]
                if BACKEND.image_data_format() == "channels_last"
                else [True, False, True, True]
            )
            se_tensor = LAYERS.Lambda(
                lambda x: BACKEND.pattern_broadcast(x, pattern),
                name=prefix + "se_broadcast",
            )(se_tensor)
        x_in = LAYERS.multiply([x_in, se_tensor], name=prefix + "se_excite")

    # Output phase
    x_in = LAYERS.Conv2D(
        block_args.output_filters,
        1,
        padding="same",
        use_bias=False,
        kernel_initializer=CONV_KERNEL_INITIALIZER,
        name=prefix + "project_conv",
    )(x_in)
    x_in = LAYERS.BatchNormalization(axis=bn_axis, name=prefix + "project_bn")(x_in)
    if (
        block_args.id_skip
        and all(s == 1 for s in block_args.strides)
        and block_args.input_filters == block_args.output_filters
    ):
        if drop_rate and (drop_rate > 0):
            x_in = Dropout(
                drop_rate, noise_shape=(None, 1, 1, 1), name=prefix + "drop"
            )(x_in)
        x_in = LAYERS.add([x_in, inputs], name=prefix + "add")

    return x_in


def efficientnet_base(  # pylint: disable=too-many-arguments, too-many-locals, too-many-branches
    width_coefficient: float,
    depth_coefficient: float,
    default_resolution: int,
    drop_connect_rate: float = 0.2,
    depth_divisor: int = 8,
    blocks_args=DEFAULT_BLOCKS_ARGS,
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """Instantiates the EfficientNet architecture using given scaling coefficients.
    Optionally loads weights pre-trained on ImageNet.
    Note that the data format convention used by the model is
    the one specified in your Keras config at `~/.keras/keras.json`.
    # Arguments
        width_coefficient: float, scaling coefficient for network width.
        depth_coefficient: float, scaling coefficient for network depth.
        default_resolution: int, default input image size.
        dropout_rate: float, dropout rate before final classifier layer.
        drop_connect_rate: float, dropout rate at skip connections.
        depth_divisor: int.
        blocks_args: A tuple of BlockArgs to construct block modules.
        model_name: string, model name.
        include_top: whether to include the fully-connected
            layer at the top of the network.
        weights: one of `None` (random initialization),
              'imagenet' (pre-training on ImageNet),
              or the path to the weights file to be loaded.
        input_tensor: optional Keras tensor
            (i.e. output of `layers.Input()`)
            to use as image input for the model.
        input_shape: optional shape tuple, only to be specified
            if `include_top` is False.
            It should have exactly 3 inputs channels.
        pooling: optional pooling mode for feature extraction
            when `include_top` is `False`.
            - `None` means that the output of the model will be
                the 4D tensor output of the
                last convolutional layer.
            - `avg` means that global average pooling
                will be applied to the output of the
                last convolutional layer, and thus
                the output of the model will be a 2D tensor.
            - `max` means that global max pooling will
                be applied.
        classes: optional number of classes to classify images
            into, only to be specified if `include_top` is True, and
            if no `weights` argument is specified.
    # Returns
        A Keras model instance.
    # Raises
        ValueError: in case of invalid argument for `weights`,
            or invalid input shape.
    """
    global BACKEND, LAYERS, MODELS, KERAS_UTILS  # pylint: disable=global-statement
    BACKEND, LAYERS, MODELS, KERAS_UTILS = get_submodules_from_kwargs(kwargs)
    features = []
    if not (weights in {"imagenet", None} or os.path.exists(weights)):
        raise ValueError(
            "The `weights` argument should be either "
            "`None` (random initialization), `imagenet` "
            "(pre-training on ImageNet), "
            "or the path to the weights file to be loaded."
        )

    if weights == "imagenet" and include_top and classes != 1000:
        raise ValueError(
            'If using `weights` as `"imagenet"` with `include_top`'
            " as true, `classes` should be 1000"
        )

    # Determine proper input shape
    input_shape = obtain_input_shape(
        input_shape,
        default_size=default_resolution,
        min_size=32,
        data_format=BACKEND.image_data_format(),
        require_flatten=include_top,
        weights=weights,
    )

    if input_tensor is None:
        img_input = LAYERS.Input(shape=input_shape)
    else:
        if BACKEND.backend() == "tensorflow":
            from tensorflow.python.keras.backend import (  # pylint: disable=import-outside-toplevel
                is_keras_tensor,
            )
        else:
            is_keras_tensor = BACKEND.is_keras_tensor
        if not is_keras_tensor(input_tensor):
            img_input = LAYERS.Input(tensor=input_tensor, shape=input_shape)
        else:
            img_input = input_tensor

    bn_axis = 3 if BACKEND.image_data_format() == "channels_last" else 1
    activation = get_swish(**kwargs)

    # Build stem
    x_in = img_input
    x_in = LAYERS.Conv2D(
        round_filters(32, width_coefficient, depth_divisor),
        3,
        strides=(2, 2),
        padding="same",
        use_bias=False,
        kernel_initializer=CONV_KERNEL_INITIALIZER,
        name="stem_conv",
    )(x_in)
    x_in = LAYERS.BatchNormalization(axis=bn_axis, name="stem_bn")(x_in)
    x_in = LAYERS.Activation(activation, name="stem_activation")(x_in)
    # Build blocks
    num_blocks_total = sum(block_args.num_repeat for block_args in blocks_args)
    block_num = 0
    for idx, block_args in enumerate(blocks_args):
        assert block_args.num_repeat > 0
        # Update block input and output filters based on depth multiplier.
        block_args = block_args._replace(
            input_filters=round_filters(
                block_args.input_filters, width_coefficient, depth_divisor
            ),
            output_filters=round_filters(
                block_args.output_filters, width_coefficient, depth_divisor
            ),
            num_repeat=round_repeats(block_args.num_repeat, depth_coefficient),
        )

        # The first block needs to take care of stride and filter size increase.
        drop_rate = drop_connect_rate * float(block_num) / num_blocks_total
        x_in = mb_conv_block(
            x_in,
            block_args,
            activation=activation,
            drop_rate=drop_rate,
            prefix="block{}a_".format(idx + 1),
        )
        block_num += 1
        if block_args.num_repeat > 1:
            # pylint: disable=protected-access
            block_args = block_args._replace(
                input_filters=block_args.output_filters, strides=[1, 1]
            )
            # pylint: enable=protected-access
            for bidx in xrange(block_args.num_repeat - 1):
                drop_rate = drop_connect_rate * float(block_num) / num_blocks_total
                block_prefix = "block{}{}_".format(
                    idx + 1, string.ascii_lowercase[bidx + 1]
                )
                x_in = mb_conv_block(
                    x_in,
                    block_args,
                    activation=activation,
                    drop_rate=drop_rate,
                    prefix=block_prefix,
                )
                block_num += 1
        if idx < len(blocks_args) - 1 and blocks_args[idx + 1].strides[0] == 2:
            features.append(x_in)
        elif idx == len(blocks_args) - 1:
            features.append(x_in)
    return features


def efficientnet_b0(
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """EfficientNet-B0 model"""
    return efficientnet_base(
        1.0,
        1.0,
        224,
        0.2,
        include_top=include_top,
        weights=weights,
        input_tensor=input_tensor,
        input_shape=input_shape,
        classes=classes,
        **kwargs
    )


def efficientnet_b1(
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """EfficientNet-B1 model"""
    return efficientnet_base(
        1.0,
        1.1,
        240,
        0.2,
        include_top=include_top,
        weights=weights,
        input_tensor=input_tensor,
        input_shape=input_shape,
        classes=classes,
        **kwargs
    )


def efficientnet_b2(
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """EfficientNet-B2 model"""
    return efficientnet_base(
        1.1,
        1.2,
        260,
        0.3,
        include_top=include_top,
        weights=weights,
        input_tensor=input_tensor,
        input_shape=input_shape,
        classes=classes,
        **kwargs
    )


def efficientnet_b3(
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """EfficientNet-B3 model"""
    return efficientnet_base(
        1.2,
        1.4,
        300,
        0.3,
        include_top=include_top,
        weights=weights,
        input_tensor=input_tensor,
        input_shape=input_shape,
        classes=classes,
        **kwargs
    )


def efficientnet_b4(
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """EfficientNet-B4 model"""
    return efficientnet_base(
        1.4,
        1.8,
        380,
        0.4,
        include_top=include_top,
        weights=weights,
        input_tensor=input_tensor,
        input_shape=input_shape,
        classes=classes,
        **kwargs
    )


def efficientnet_b5(
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """EfficientNet-B5 model"""
    return efficientnet_base(
        1.6,
        2.2,
        456,
        0.4,
        include_top=include_top,
        weights=weights,
        input_tensor=input_tensor,
        input_shape=input_shape,
        classes=classes,
        **kwargs
    )


def efficientnet_b6(
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """EfficientNet-B6 model"""
    return efficientnet_base(
        1.8,
        2.6,
        528,
        0.5,
        include_top=include_top,
        weights=weights,
        input_tensor=input_tensor,
        input_shape=input_shape,
        classes=classes,
        **kwargs
    )


def efficientnet_b7(
    include_top: bool = True,
    weights: str = "imagenet",
    input_tensor: Union[None, tf.Tensor] = None,
    input_shape: Union[None, Tuple[int, int, int]] = None,
    classes: int = 1000,
    **kwargs: Any
) -> List[tf.Tensor]:
    """EfficientNet-B7 model"""
    return efficientnet_base(
        2.0,
        3.1,
        600,
        0.5,
        include_top=include_top,
        weights=weights,
        input_tensor=input_tensor,
        input_shape=input_shape,
        classes=classes,
        **kwargs
    )


setattr(efficientnet_b0, "__doc__", efficientnet_base.__doc__)
setattr(efficientnet_b1, "__doc__", efficientnet_base.__doc__)
setattr(efficientnet_b2, "__doc__", efficientnet_base.__doc__)
setattr(efficientnet_b3, "__doc__", efficientnet_base.__doc__)
setattr(efficientnet_b4, "__doc__", efficientnet_base.__doc__)
setattr(efficientnet_b5, "__doc__", efficientnet_base.__doc__)
setattr(efficientnet_b6, "__doc__", efficientnet_base.__doc__)
setattr(efficientnet_b7, "__doc__", efficientnet_base.__doc__)
