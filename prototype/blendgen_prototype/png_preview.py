"""Small lossless RGB8 PNG reader/writer for dependency-free box previews.

The clean render is never modified. Input is the RGB8 PNG produced by this
exporter; original color-management chunks are retained in the preview.
"""
import struct
import zlib
from pathlib import Path

SIGNATURE=b'\x89PNG\r\n\x1a\n'


def paeth(a,b,c):
    p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
    return a if pa<=pb and pa<=pc else b if pb<=pc else c


def read_png(path):
    data=Path(path).read_bytes()
    if not data.startswith(SIGNATURE):raise ValueError('Render is not a PNG')
    position=8;compressed=[];ancillary=[];header=None
    while position<len(data):
        length=struct.unpack('>I',data[position:position+4])[0]
        kind=data[position+4:position+8];payload=data[position+8:position+8+length]
        if kind==b'IHDR':header=payload
        elif kind==b'IDAT':compressed.append(payload)
        elif kind in (b'sRGB',b'gAMA',b'cHRM',b'iCCP',b'pHYs'):ancillary.append((kind,payload))
        position+=length+12
        if kind==b'IEND':break
    if header is None:raise ValueError('PNG header missing')
    width,height,depth,color,compression,filter_method,interlace=struct.unpack('>IIBBBBB',header)
    if (depth,color,compression,filter_method,interlace)!=(8,2,0,0,0):
        raise ValueError('Preview expects a non-interlaced RGB8 PNG')
    stride=width*3;raw=zlib.decompress(b''.join(compressed))
    if len(raw)!=(stride+1)*height:raise ValueError('PNG pixel data is incomplete')
    pixels=bytearray(stride*height);prior=bytearray(stride)
    for y in range(height):
        start=y*(stride+1);kind=raw[start];row=bytearray(raw[start+1:start+1+stride])
        if kind not in range(5):raise ValueError('Unsupported PNG row filter')
        for i in range(stride):
            a=row[i-3] if i>=3 else 0;b=prior[i];c=prior[i-3] if i>=3 else 0
            prediction=(0,a,b,(a+b)//2,paeth(a,b,c))[kind]
            row[i]=(row[i]+prediction)&255
        pixels[y*stride:(y+1)*stride]=row;prior=row
    return width,height,pixels,ancillary


def chunk(kind,payload):
    return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)


def write_png(path,width,height,pixels,ancillary):
    stride=width*3
    raw=b''.join(b'\0'+pixels[y*stride:(y+1)*stride] for y in range(height))
    data=SIGNATURE+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))
    data+=b''.join(chunk(kind,payload) for kind,payload in ancillary)
    data+=chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
    Path(path).write_bytes(data)


def draw_preview(clean_path,preview_path,yolo):
    width,height,pixels,ancillary=read_png(clean_path)
    _,cx,cy,bw,bh=yolo;cx,cy,bw,bh=map(float,(cx,cy,bw,bh))
    left=max(0,min(width-1,int((cx-bw/2)*width)))
    right=max(0,min(width-1,int((cx+bw/2)*width)))
    top=max(0,min(height-1,int((cy-bh/2)*height)))
    bottom=max(0,min(height-1,int((cy+bh/2)*height)))
    color=bytes((30,235,100));thickness=max(2,round(min(width,height)/300))
    for y in range(top,bottom+1):
        for x in range(left,right+1):
            if x-left<thickness or right-x<thickness or y-top<thickness or bottom-y<thickness:
                i=(y*width+x)*3;pixels[i:i+3]=color
    # Small '0' class-ID tag outside the rectangle; classes.txt maps 0 to its name.
    for row,bits in enumerate(('111','101','101','101','111')):
        for col,bit in enumerate(bits):
            if bit!='1':continue
            for dy in range(2):
                for dx in range(2):
                    x=left+col*2+dx;y=max(0,top-13)+row*2+dy
                    if x<width and y<height:
                        i=(y*width+x)*3;pixels[i:i+3]=color
    write_png(preview_path,width,height,pixels,ancillary)
    return width,height
