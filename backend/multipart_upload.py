import tempfile
from dataclasses import dataclass
from email.message import Message


READ_CHUNK_BYTES = 64 * 1024
MAX_HEADER_BYTES = 64 * 1024
SPOOL_MEMORY_BYTES = 1024 * 1024


@dataclass
class UploadedFile:
    filename: str
    file: object


class MultipartStreamParser:
    def __init__(self, stream, content_length, boundary):
        self.stream = stream
        self.remaining = content_length
        self.boundary = b"--" + boundary
        self.buffer = b""

    def parse(self):
        first_line = self.readline().rstrip(b"\r\n")
        if first_line != self.boundary:
            raise ValueError("multipart 起始边界无效")
        files = []
        try:
            while True:
                headers = self.read_headers()
                disposition = headers.get("Content-Disposition", "")
                filename = headers.get_param("filename", header="Content-Disposition") if disposition else None
                body = self.read_part_body()
                boundary_line = self.readline().rstrip(b"\r\n")
                if filename:
                    files.append(UploadedFile(filename=filename, file=body))
                else:
                    body.close()
                if boundary_line == self.boundary + b"--":
                    break
                if boundary_line != self.boundary:
                    raise ValueError("multipart 分隔边界无效")
            if not files:
                raise ValueError("没有收到文件")
            return files
        except Exception:
            for item in files:
                item.file.close()
            raise

    def read_headers(self):
        raw_headers = bytearray()
        while True:
            line = self.readline()
            if line in {b"\r\n", b"\n"}:
                break
            raw_headers.extend(line)
            if len(raw_headers) > MAX_HEADER_BYTES:
                raise ValueError("multipart 请求头过大")
        message = Message()
        for raw_line in bytes(raw_headers).decode("utf-8", errors="replace").splitlines():
            name, separator, value = raw_line.partition(":")
            if separator:
                message[name.strip()] = value.strip()
        return message

    def read_part_body(self):
        delimiter = b"\r\n" + self.boundary
        keep_bytes = len(delimiter) + 4
        output = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b")
        while True:
            boundary_index = self.find_boundary(delimiter)
            if boundary_index is not None:
                output.write(self.buffer[:boundary_index])
                self.buffer = self.buffer[boundary_index + 2 :]
                output.seek(0)
                return output
            if len(self.buffer) > keep_bytes:
                output.write(self.buffer[:-keep_bytes])
                self.buffer = self.buffer[-keep_bytes:]
            if not self.read_more():
                output.close()
                raise ValueError("multipart 文件内容不完整")

    def find_boundary(self, delimiter):
        search_from = 0
        while True:
            boundary_index = self.buffer.find(delimiter, search_from)
            if boundary_index < 0:
                return None
            suffix_start = boundary_index + len(delimiter)
            suffix = self.buffer[suffix_start : suffix_start + 2]
            if suffix in {b"\r\n", b"--"}:
                return boundary_index
            if len(suffix) < 2 and self.remaining > 0:
                return None
            search_from = boundary_index + len(delimiter)

    def readline(self):
        while True:
            line_end = self.buffer.find(b"\n")
            if line_end >= 0:
                line = self.buffer[: line_end + 1]
                self.buffer = self.buffer[line_end + 1 :]
                return line
            if len(self.buffer) > MAX_HEADER_BYTES:
                raise ValueError("multipart 行过长")
            if not self.read_more():
                if self.buffer:
                    line, self.buffer = self.buffer, b""
                    return line
                raise ValueError("multipart 请求意外结束")

    def read_more(self):
        if self.remaining <= 0:
            return False
        chunk = self.stream.read(min(READ_CHUNK_BYTES, self.remaining))
        if not chunk:
            self.remaining = 0
            return False
        self.remaining -= len(chunk)
        self.buffer += chunk
        return True


def parse_multipart_upload(stream, headers, content_length):
    content_type = Message()
    content_type["Content-Type"] = headers.get("Content-Type", "")
    if content_type.get_content_type() != "multipart/form-data":
        raise ValueError("请求不是有效的 multipart/form-data")
    boundary = content_type.get_param("boundary", header="Content-Type")
    if not boundary:
        raise ValueError("multipart 请求缺少 boundary")
    return MultipartStreamParser(stream, content_length, boundary.encode("utf-8")).parse()
