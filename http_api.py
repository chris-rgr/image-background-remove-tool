"""
Name: Http Flask API
Description: This file contains an interface for interacting with this tool through http requests.
Version: [release][3.3]
Source url: https://github.com/OPHoperHPO/image-background-remove-tool
Authors: Anodev (OPHoperHPO)[https://github.com/OPHoperHPO], Pubkey [https://github.com/pubkey].
License: Apache License 2.0
License:
   Copyright 2020 OPHoperHPO

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""

# Built-in libraries
import argparse
import base64
import io
import os
import time
import zipfile
import multiprocessing
from copy import deepcopy

# 3rd party libraries
import psutil
import requests
from PIL import Image, ImageColor
from flask import Flask, request, send_file, jsonify, make_response
from flask_cors import CORS

# Libraries of this project
from libs.networks import model_detect
from libs.postprocessing import method_detect as postprocessing_detect
from libs.preprocessing import method_detect as preprocessing_detect
from libs.strings import MODELS_NAMES, POSTPROCESS_METHODS, PREPROCESS_METHODS, ARGS
from libs.args import str2bool

# parse args and set defaults
parser = argparse.ArgumentParser(description="HTTP API to remove background from images", usage="")
parser.add_argument('-m', required=False,
                    help=ARGS["-m"][1],
                    action="store", dest="model_name", default=MODELS_NAMES[0]
                    )
parser.add_argument("-auth", type=str2bool, nargs='?',
                    const=True, default=False,
                    dest="auth",
                    help="Enable or Disable the authentication"
                    )
parser.add_argument('-port', required=False,
                    help="Port",
                    action="store", dest="port", default=5000
                    )
parser.add_argument('-host', required=False,
                    help="Host",
                    action="store", dest="host", default="0.0.0.0"
                    )
parser.add_argument('-prep', required=False,
                    help=ARGS["-prep"][1],
                    action="store", dest="prep", default=PREPROCESS_METHODS[0])
parser.add_argument('-postp', required=False,
                    help=ARGS["-postp"][1],
                    action="store", dest="postp", default=POSTPROCESS_METHODS[0])
args = parser.parse_args()

if "IS_DOCKER_CONTAINER" in os.environ.keys():
    class Config:
        """Config object"""
        model = os.environ["MODEL"]  # u2net
        prep_method = os.environ["PREPROCESSING"]  # None
        post_method = os.environ["POSTPROCESSING"]  # fba
        auth = str2bool(os.environ["AUTH"])  # Token Client Authentication
        port = int(os.environ["PORT"])  # 5000
        host = os.environ["HOST"]  # 0.0.0.0
        admin_token = os.environ["ADMIN_TOKEN"]  # Admin token
        allowed_tokens = list(os.environ["ALLOWED_TOKENS_PYTHON_ARR"])  # All allowed tokens
        procs_num_max = 1  # The maximum number of processes that can process a request
else:
    class Config:
        """Config object"""
        model = args.model_name  # u2net
        prep_method = args.prep  # None
        post_method = args.postp  # fba
        auth = args.auth  # Token Client Authentication
        port = args.port  # 5000
        host = args.host  # 0.0.0.0
        admin_token = "admin"  # Admin token
        allowed_tokens = ["test"]  # All allowed tokens
        procs_num_max = 1  # The maximum number of processes that can process a request

# Init vars
config = Config()  # Init config object
app = Flask(__name__)  # Init flask app
CORS(app)  # Enable Cross-origin resource sharing
start_time = time.time()  # This time is needed to get uptime
procs = 0  # Number of running processes

default_settings = \
    {  # API settings by default. See https://www.remove.bg/api for more details.
        "image_file_b64": "",
        "image_url": "",
        "size": "preview",
        "type": "auto",
        "format": "auto",
        "roi": "",
        "crop": "false",
        "crop_margin": "0px",
        "scale": "original",
        "position": "original",
        "channels": "rgba",
        "add_shadow": "false",  # Not supported at the moment
        "semitransparency": "false",  # Not supported at the moment
        "bg_color": "",
        "bg_image_url": ""
    }


# noinspection PyBroadException
@app.route("/api/removebg", methods=["POST"])
def removebg():
    """
    API method for removing background from image.
    :return: Image or error or zip file
    """
    global procs
    h = dict(request.headers)
    headers = dict()
    for key in h:
        val = h[key]
        headers[key.lower()] = val
    if "x-api-key" in headers.keys() or config.auth is False:
        if headers["x-api-key"] in config.allowed_tokens \
                or config.auth is False or headers["x-api-key"] == config.admin_token:
            if "content-type" in headers.keys():
                if "multipart/form-data" in request.content_type:
                    try:
                        params = deepcopy(default_settings)
                        data = dict(request.form)
                        for key in data:
                            params[key] = data[key]
                    except BaseException:
                        return error_dict("Something went wrong"), 400
                    if procs >= config.procs_num_max:
                        while procs >= config.procs_num_max:
                            pass
                    if procs < config.procs_num_max:
                        procs += 1
                        q = multiprocessing.Queue()
                        proc = multiprocessing.Process(target=process_remove_bg,
                                                       args=(params, request, q, False,))
                        proc.start()
                        procs -= 1
                    return q.get()
                elif request.content_type == "application/x-www-form-urlencoded":
                    try:
                        params = deepcopy(default_settings)
                        data = dict(request.form)
                        for key in data:
                            params[key] = data[key]
                    except BaseException:
                        return error_dict("Something went wrong"), 400
                    if procs >= config.procs_num_max:
                        while procs >= config.procs_num_max:
                            pass
                    if procs < config.procs_num_max:
                        procs += 1
                        q = multiprocessing.Queue()
                        proc = multiprocessing.Process(target=process_remove_bg,
                                                       args=(params, request, q, True,))
                        proc.start()
                        procs -= 1
                    return q.get()
                elif request.content_type == "application/json":
                    try:
                        params = deepcopy(default_settings)
                        data = dict(request.get_json())
                        for key in data:
                            params[key] = data[key]
                    except BaseException:
                        return error_dict("Something went wrong"), 400
                    if procs >= config.procs_num_max:
                        while procs >= config.procs_num_max:
                            pass
                    if procs < config.procs_num_max:
                        procs += 1
                        q = multiprocessing.Queue()
                        proc = multiprocessing.Process(target=process_remove_bg,
                                                       args=(params, request, q, True,))
                        proc.start()
                        procs -= 1
                    return q.get()
                else:
                    return error_dict("Invalid request content type"), 400
            else:
                return error_dict("Invalid request content type"), 400
        else:
            return error_dict("Authentication failed"), 403
    else:
        return error_dict("Missing API Key"), 403


@app.route("/api/status", methods=["GET"])
def status():
    """
    Returns the current server status.
    """
    h = dict(request.headers)
    headers = dict()
    for key in h:
        val = h[key]
        headers[key.lower()] = val
    if "x-api-key" in headers.keys() or config.auth is False:
        if config.auth is False or headers["x-api-key"] == config.admin_token:
            this = psutil.Process(os.getpid())
            data = {
                "status": {
                    "program": {
                        "used_model": config.model,
                        "prep_method": config.prep_method,
                        "post_method": config.post_method,
                        "use_auth": config.auth
                    },
                    "server": {
                        "process_name": this.name(),
                        "cpu_percent": this.cpu_percent(),
                        "used_memory": this.memory_info(),
                        "uptime": int(time.time() - start_time)
                    }
                }
            }
            resp = jsonify(data)
            resp.headers["X-Credits-Charged"] = 0
            return resp, 200
        else:
            return error_dict("Authentication failed"), 403
    else:
        return error_dict("Missing API Key"), 403


@app.route("/api/account")
def account():
    """
    Stub for compatibility with remove.bg api libraries
    """
    return jsonify({"data": {"attributes": {
        "credits": {"total": 99999, "subscription": 99999, "payg": 99999, "enterprise": 99999},
        "api": {"free_calls": 99999, "sizes": "all"}}}}), 200


@app.route('/')
def root():
    """
    Main page
    :return: text
    """
    return 'image-background-remove-tool API v3.3'


def error_dict(error_text: str):
    """
    Generates a dictionary containing $error_text error
    :param error_text: Error text
    :return: error dictionary
    """
    resp = jsonify({"errors": [{"title": error_text}]})
    resp.headers["X-Credits-Charged"] = 0
    return resp


# TODO Make a queue for processing requests and a method for quickly changing models and methods of image processing
# TODO Move initialization somewhere else
# noinspection PyBroadException
def process_remove_bg(params, request, queue, is_json_or_www_encoded=False, ):
    """
    Handles a request to the removebg api method
    :param params: parameters
    :param request: flask request
    :param queue: Queue for sending a response
    :param is_json_or_www_encoded: is "json" or "x-www-form-urlencoded" content-type
    :return:
    """
    # Tool initialization
    prep_method = preprocessing_detect(config.prep_method)
    post_method = postprocessing_detect(config.post_method)
    model = model_detect(config.model)

    image_loaded = False
    image = None
    if "image_file_b64" in params.keys() and image_loaded is False:
        value = params["image_file_b64"]
        if len(value) > 0:
            try:
                image = Image.open(io.BytesIO(base64.b64decode(value)))
            except BaseException:
                queue.put((error_dict("Error decode image!"), 400))
                exit(0)
            image_loaded = True
        else:
            if "image_url" in params.keys() and image_loaded is False:
                value = params["image_url"]
                if len(value) > 0:
                    try:
                        image = Image.open(io.BytesIO(requests.get(value).content))
                        image_loaded = True
                    except BaseException:
                        queue.put((error_dict("Error download image!"), 400))
                        exit(0)
    if not is_json_or_www_encoded:
        if image_loaded is False:
            if 'image_file' not in request.files:
                queue.put((error_dict("File not found"), 400))
                exit(0)
            image = request.files['image_file'].read()
            if len(image) == 0:
                queue.put((error_dict("Empty image"), 400))
                exit(0)
            image = Image.open(io.BytesIO(image))  # Convert bytes to PIL image

    if "size" in params.keys():
        value = params["size"]
        if value == "preview" or value == "small" or value == "regular":
            image.thumbnail((625, 400), resample=Image.ANTIALIAS)  # 0.25 mp
        elif value == "medium":
            image.thumbnail((1504, 1000), resample=Image.ANTIALIAS)  # 1.5 mp
        elif value == "hd":
            image.thumbnail((2000, 2000), resample=Image.ANTIALIAS)  # 2.5 mp
        else:
            image.thumbnail((6250, 4000), resample=Image.ANTIALIAS)  # 25 mp

    roi_box = [0, 0, image.size[0], image.size[1]]
    if "type" in params.keys():
        value = params["type"]
        if len(value) > 0:
            if prep_method:
                prep_method.foreground = value

    if "roi" in params.keys():
        value = params["roi"]
        value = value.split(" ")
        if len(value) == 4:
            for i, coord in enumerate(value):
                if "px" in coord:
                    coord = coord.replace("px", "")
                    try:
                        coord = int(coord)
                    except BaseException:
                        queue.put((error_dict("Error converting roi coordinate string to number!"), 400))
                        exit(0)
                    if (i == 0 or i == 2) and coord > image.size[0]:
                        queue.put((error_dict(
                            "The roi coordinate cannot be larger than the image size."), 400))
                        exit(0)
                    elif (i == 1 or i == 3) and coord > image.size[1]:
                        queue.put((error_dict(
                            "The roi coordinate cannot be larger than the image size."), 400))
                        exit(0)
                    roi_box[i] = int(coord)
                elif "%" in coord:
                    coord = coord.replace("%", "")
                    try:
                        coord = int(coord)
                    except BaseException:
                        queue.put((error_dict("Error converting roi coordinate string to number!"), 400))
                        exit(0)
                    if coord > 100:
                        queue.put((error_dict("The coordinate cannot be more than 100%"), 400))
                        exit(0)
                    elif coord < 0:
                        queue.put((error_dict("Coordinate cannot be less than 0%"), 400))
                        exit(0)
                    if i == 0 or i == 2:
                        coord = int(image.size[0] * coord / 100)
                    elif i == 1 or i == 3:
                        coord = int(image.size[1] * coord / 100)
                    roi_box[i] = coord
                else:
                    queue.put((error_dict("Something wrong with roi coordinates!"), 400))
                    exit(0)

    new_image = image.copy()
    new_image = new_image.crop(roi_box)
    new_image = model.process_image(new_image, prep_method, post_method)

    if prep_method:
        prep_method.foreground = "auto"

    scaled = False
    if "scale" in params.keys():
        value = params["scale"]
        if "%" in value:
            value = value.replace("%", "")
            try:
                value = int(value)
            except BaseException:
                queue.put((error_dict("Error converting scale string to number!"), 400))
                exit(0)
            if value > 100:
                queue.put((error_dict("The scale cannot be more than 100%"), 400))
                exit(0)
            elif value <= 0:
                queue.put((error_dict("scale cannot be less than 1%"), 400))
                exit(0)
            new_image.thumbnail((int(image.size[0] * value / 100),
                                 int(image.size[1] * value / 100)), resample=Image.ANTIALIAS)
            scaled = True
    if "crop" in params.keys():
        value = params["crop"]
        if value == "true" or value is True:
            new_image = new_image.crop(new_image.getbbox())
            if "crop_margin" in params.keys():
                crop_margin = params["crop_margin"]
                if "px" in crop_margin:
                    crop_margin = crop_margin.replace("px", "")
                    try:
                        crop_margin = int(crop_margin)
                    except BaseException:
                        queue.put((error_dict("Error converting crop_margin string to number!"), 400))
                        exit(0)
                    crop_margin = abs(crop_margin)
                    if crop_margin > 500:
                        queue.put((error_dict(
                            "The crop_margin cannot be larger than the original image size."), 400))
                        exit(0)
                    new_image = add_margin(new_image, crop_margin,
                                           crop_margin, crop_margin, crop_margin, (0, 0, 0, 0))
                elif "%" in crop_margin:
                    crop_margin = crop_margin.replace("%", "")
                    try:
                        crop_margin = int(crop_margin)
                    except BaseException:
                        queue.put((error_dict("Error converting crop_margin string to number!"), 400))
                        exit(0)
                    if crop_margin > 100:
                        queue.put((error_dict("The crop_margin cannot be more than 100%"), 400))
                        exit(0)
                    elif crop_margin < 0:
                        queue.put((error_dict("Crop_margin cannot be less than 0%"), 400))
                        exit(0)
                    new_image = add_margin(new_image, int(new_image.size[1] * crop_margin / 100),
                                           int(new_image.size[0] * crop_margin / 100),
                                           int(new_image.size[1] * crop_margin / 100),
                                           int(new_image.size[0] * crop_margin / 100), (0, 0, 0, 0))
        else:
            if "position" in params.keys() and scaled is False:
                value = params["position"]
                value = value.split(" ")
                if len(value) == 1:
                    value = value[0]
                    if "%" in value:
                        value = value.replace("%", "")
                        try:
                            value = int(value)
                        except BaseException:
                            queue.put((error_dict("Error converting position string to number!"), 400))
                            exit(0)
                        if value > 100:
                            queue.put((error_dict("The position cannot be more than 100%"), 400))
                            exit(0)
                        elif value < 0:
                            queue.put((error_dict("position cannot be less than 0%"), 400))
                            exit(0)
                        new_image = trans_paste(Image.new("RGBA", image.size), new_image,
                                                (int(image.size[0] * value / 100),
                                                 int(image.size[1] * value / 100)))
                    else:
                        new_image = trans_paste(Image.new("RGBA", image.size), new_image, roi_box)
                elif len(value) == 2:
                    for i, val in enumerate(value):
                        try:
                            val = int(val)
                        except BaseException:
                            queue.put((error_dict("Error converting position string to number!"), 400))
                            exit(0)
                        if val < 0:
                            queue.put((error_dict("position cannot be less than 0px"), 400))
                            exit(0)
                        if i == 0 and val > image.size[0]:
                            queue.put((error_dict("position cannot be greater than image size"), 400))
                            exit(0)
                        elif i == 1 and val > image.size[1]:
                            queue.put((error_dict("position cannot be greater than image size"), 400))
                            exit(0)
                        value[i] = val
                    new_image = trans_paste(Image.new("RGBA", image.size), new_image,
                                            (value[0], value[1]))
                else:
                    new_image = trans_paste(Image.new("RGBA", image.size), new_image, roi_box)
            elif scaled is False:
                new_image = trans_paste(Image.new("RGBA", image.size), new_image, roi_box)
    if "channels" in params.keys():
        value = params["channels"]
        if value == "alpha":
            new_image = __extact_alpha_channel__(new_image)
        else:
            bg_chaged = False
            if "bg_color" in params.keys():
                value = params["bg_color"]
                if len(value) > 0:
                    try:
                        color = ImageColor.getcolor(value, "RGB")
                    except BaseException:
                        try:
                            color = ImageColor.getcolor("#" + value, "RGB")
                        except BaseException:
                            queue.put((error_dict("Error converting bg_color string to color tuple!"), 400))
                            exit(0)
                    bg = Image.new("RGBA", new_image.size, color)
                    bg = trans_paste(bg, new_image, (0, 0))
                    new_image = bg.copy()
                    bg_chaged = True
            if "bg_image_url" in params.keys() and bg_chaged is False:
                value = params["bg_image_url"]
                if len(value) > 0:
                    try:
                        bg = Image.open(io.BytesIO(requests.get(value).raw))
                    except BaseException:
                        queue.put((error_dict("Error download background image!"), 400))
                        exit(0)
                    bg = bg.resize(new_image.size)
                    bg = trans_paste(bg, new_image, (0, 0))
                    new_image = bg.copy()
                    bg_chaged = True
            if not is_json_or_www_encoded:
                if "bg_image_file" in request.files and bg_chaged is False:
                    bg = request.files['image_file'].read()
                    if len(bg) == 0:
                        queue.put((error_dict("Empty background image"), 400))
                        exit(0)
                    bg = Image.open(io.BytesIO(bg))  # Convert bytes to PIL image
                    bg = bg.resize(new_image.size)
                    bg = trans_paste(bg, new_image, (0, 0))
                    new_image = bg.copy()
    if "format" in params.keys():
        value = params["format"]
        if value == "jpg":
            new_image = new_image.convert("RGB")
            img_io = io.BytesIO()
            new_image.save(img_io, 'JPEG', quality=100)
            img_io.seek(0)
            resp = send_file(img_io, mimetype='image/jpeg')
            resp.headers["X-Credits-Charged"] = 0
            resp.headers["X-Type"] = "other"
            resp.headers["X-Width"] = new_image.size[0]
            resp.headers["X-Height"] = new_image.size[1]
            queue.put((resp))
            exit(0)
        elif value == "zip":
            mask = __extact_alpha_channel__(new_image)
            mask_buff = io.BytesIO()
            mask.save(mask_buff, 'PNG')
            mask_buff.seek(0)
            image_buff = io.BytesIO()
            image.save(image_buff, 'JPEG')
            image_buff.seek(0)
            fileobj = io.BytesIO()
            with zipfile.ZipFile(fileobj, 'w') as zip_file:
                zip_info = zipfile.ZipInfo(filename="color.jpg")
                zip_info.date_time = time.localtime(time.time())[:6]
                zip_info.compress_type = zipfile.ZIP_DEFLATED
                zip_file.writestr(zip_info, image_buff.getvalue())
                zip_info = zipfile.ZipInfo(filename="alpha.png")
                zip_info.date_time = time.localtime(time.time())[:6]
                zip_info.compress_type = zipfile.ZIP_DEFLATED
                zip_file.writestr(zip_info, mask_buff.getvalue())
            fileobj.seek(0)
            response = make_response(fileobj.read())
            response.headers.set('Content-Type', 'zip')
            response.headers.set('Content-Disposition', 'attachment',
                                 filename='no-bg.zip')
            response.headers["X-Credits-Charged"] = 0
            response.headers["X-Type"] = "other"  # TODO: Associate this with an object classifier
            response.headers["X-Width"] = new_image.size[0]
            response.headers["X-Height"] = new_image.size[1]
            queue.put((response))
            exit(0)
        else:
            buff = io.BytesIO()
            new_image.save(buff, 'PNG')
            buff.seek(0)
            resp = send_file(buff, mimetype='image/png')
            resp.headers["X-Credits-Charged"] = 0
            resp.headers["X-Type"] = "other"  # TODO: Associate this with an object classifier
            resp.headers["X-Width"] = new_image.size[0]
            resp.headers["X-Height"] = new_image.size[1]
            queue.put((resp))
            exit(0)


def trans_paste(bg_img, fg_img, box=(0, 0)):
    """
    Inserts an image into another image while maintaining transparency.
    :param bg_img: Background pil image
    :param fg_img: Foreground pil image
    :param box: Bounding box
    :return: Pil Image
    """
    fg_img_trans = Image.new("RGBA", bg_img.size)
    fg_img_trans.paste(fg_img, box, mask=fg_img)
    new_img = Image.alpha_composite(bg_img, fg_img_trans)
    return new_img


def __extact_alpha_channel__(image):
    """
    Extracts alpha channel from RGBA image
    :param image: RGBA pil image
    :return: RGB Pil image
    """
    # Extract just the alpha channel
    alpha = image.split()[-1]
    # Create a new image with an opaque black background
    bg = Image.new("RGBA", image.size, (0, 0, 0, 255))
    # Copy the alpha channel to the new image using itself as the mask
    bg.paste(alpha, mask=alpha)
    return bg.convert("RGBA")


def add_margin(pil_img, top, right, bottom, left, color):
    """
    Adds fields to the image.
    """
    width, height = pil_img.size
    new_width = width + right + left
    new_height = height + top + bottom
    result = Image.new(pil_img.mode, (new_width, new_height), color)
    result.paste(pil_img, (left, top))
    return result


if __name__ == '__main__':
    app.run(host=config.host, port=config.port)
