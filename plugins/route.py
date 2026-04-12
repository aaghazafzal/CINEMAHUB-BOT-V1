from aiohttp import web
import re
import math
import logging
import secrets
import time
import mimetypes
from aiohttp.http_exceptions import BadStatusLine
from dreamxbotz.Bot import multi_clients, work_loads, dreamxbotz
from dreamxbotz.server.exceptions import FIleNotFound, InvalidHash
from dreamxbotz.zzint import StartTime, __version__
from dreamxbotz.util.custom_dl import ByteStreamer
from dreamxbotz.util.time_format import get_readable_time
from dreamxbotz.util.render_template import render_page
from info import *


routes = web.RouteTableDef()

@routes.get("/favicon.ico")
async def favicon_route_handler(request):
    return web.FileResponse('dreamxbotz/template/favicon.ico')

@routes.get("/logo.png")
async def logo_route_handler(request):
    return web.FileResponse('frontend/dist/logo.png')

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    import jinja2
    with open("frontend/dist/index.html") as f:
        template = jinja2.Template(f.read())
    return web.Response(text=template.render(file_name=None), content_type='text/html')

routes.static('/assets', 'frontend/dist/assets')

@routes.get(r"/watch/{path:\S+}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        match = re.search(r"^([a-zA-Z0-9_-]{6})(\d+)$", path)
        if match:
            secure_hash = match.group(1)
            id = int(match.group(2))
        else:
            id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
        return web.Response(text=await render_page(id, secure_hash), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))

@routes.get(r"/{path:\S+}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        match = re.search(r"^([a-zA-Z0-9_-]{6})(\d+)$", path)
        if match:
            secure_hash = match.group(1)
            id = int(match.group(2))
        else:
            id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
        return await media_streamer(request, id, secure_hash)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))

class_cache = {}

async def media_streamer(request: web.Request, id: int, secure_hash: str):
    try:
        range_header = request.headers.get("Range", 0)
        
        if not work_loads:
             raise ValueError("Work loads mapping is empty. Clients might not be initialized.")
        
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients.get(index)
        
        if not faster_client:
             raise ValueError(f"No client found for index {index}")

        if MULTI_CLIENT:
            logging.info(f"Client {index} is now serving {request.remote}")

        if faster_client in class_cache:
            tg_connect = class_cache[faster_client]
            logging.debug(f"Using cached ByteStreamer object for client {index}")
        else:
            logging.debug(f"Creating new ByteStreamer object for client {index}")
            tg_connect = ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
            
        file_id = await tg_connect.get_file_properties(id)
        
        if not file_id:
             raise ValueError(f"Failed to retrieve file properties for ID {id}")
        
        if getattr(file_id, "unique_id", "")[:6] != secure_hash:
            logging.debug(f"Invalid hash for message with ID {id}")
            raise InvalidHash
        
        file_size = getattr(file_id, "file_size", 0)

        if range_header:
            from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1
        else:
            from_bytes = request.http_range.start or 0
            until_bytes = (request.http_range.stop or file_size) - 1

        if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
            return web.Response(
                status=416,
                body="416: Range not satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        chunk_size = 1024 * 1024
        until_bytes = min(until_bytes, file_size - 1)

        offset = from_bytes - (from_bytes % chunk_size)
        first_part_cut = from_bytes - offset
        last_part_cut = until_bytes % chunk_size + 1

        req_length = until_bytes - from_bytes + 1
        part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)
        body = tg_connect.yield_file(
            file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
        )

        mime_type = getattr(file_id, "mime_type", "application/octet-stream")
        file_name = getattr(file_id, "file_name", "file")
        if request.rel_url.query.get("download"):
            disposition = "attachment"
        else:
            disposition = "inline"

        return web.Response(
            status=206 if range_header else 200,
            body=body,
            headers={
                "Content-Type": f"{mime_type}",
                "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
                "Content-Length": str(req_length),
                "Content-Disposition": f'{disposition}; filename="{file_name}"',
                "Accept-Ranges": "bytes",
            },
        )
    except Exception as e:
        logging.exception(f"Error in media_streamer: {str(e)}")
        raise web.HTTPInternalServerError(text=f"Server Error: {str(e)}")