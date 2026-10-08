"""Embed TrueType outlines as SWF DefineFont3; uses FontTools only at UI build time."""
import struct,zlib
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen

class Bits:
 def __init__(self):self.bits=[]
 def u(self,v,n):self.bits.extend((v>>i)&1 for i in range(n-1,-1,-1))
 def s(self,v,n):self.u(v&((1<<n)-1),n)
 def bytes(self):
  while len(self.bits)%8:self.bits.append(0)
  return bytes(sum(self.bits[i+j]<<(7-j) for j in range(8)) for i in range(0,len(self.bits),8))
def width(*vals):return max(2,max(abs(v).bit_length()+1 for v in vals))
def rect(x0,x1,y0,y1):
 b=Bits();n=width(x0,x1,y0,y1);b.u(n,5)
 for v in (x0,x1,y0,y1):b.s(v,n)
 return b.bytes()
class ShapePen(BasePen):
 def __init__(self,gs,scale):super().__init__(gs);self.b=Bits();self.b.u(1,4);self.b.u(0,4);self.x=0;self.y=0;self.scale=scale;self.points=[]
 def point(self,p):return round(p[0]*self.scale),round(-p[1]*self.scale)
 def _moveTo(self,p):
  x,y=self.point(p);self.points.append((x,y));n=width(x,y);self.b.u(0,1);self.b.u(3,5);self.b.u(n,5);self.b.s(x,n);self.b.s(y,n);self.b.u(1,1);self.x=x;self.y=y
 def _lineTo(self,p):
  x,y=self.point(p);dx=x-self.x;dy=y-self.y;self.points.append((x,y))
  if dx==0 and dy==0:return
  n=max(2,width(dx,dy));self.b.u(1,1);self.b.u(1,1);self.b.u(n-2,4);self.b.u(1,1);self.b.s(dx,n);self.b.s(dy,n);self.x=x;self.y=y
 def _qCurveToOne(self,p1,p2):
  cx,cy=self.point(p1);x,y=self.point(p2);vals=(cx-self.x,cy-self.y,x-cx,y-cy);self.points.extend([(cx,cy),(x,y)]);n=width(*vals)
  self.b.u(1,1);self.b.u(0,1);self.b.u(n-2,4)
  for v in vals:self.b.s(v,n)
  self.x=x;self.y=y
 def _closePath(self):pass
 def _endPath(self):pass
 def finish(self):self.b.u(0,6);return self.b.bytes()
def tag(kind,data):return struct.pack('<HI',(kind<<6)|63,len(data))+data

def embed(swf:Path,ttf:Path):
 font=TTFont(ttf);gs=font.getGlyphSet();scale=20480/font['head'].unitsPerEm;cmap=font.getBestCmap();codes=sorted(set(range(32,127))|set(range(160,256))|{0x20ac})
 shapes=[];bounds=[];adv=[]
 for code in codes:
  name=cmap.get(code,'.notdef');pen=ShapePen(gs,scale);gs[name].draw(pen);shapes.append(pen.finish());pts=pen.points or [(0,0)];bounds.append(rect(min(x for x,y in pts),max(x for x,y in pts),min(y for x,y in pts),max(y for x,y in pts)));adv.append(round(gs[name].width*scale))
 name=b'ModMaster Sans';count=len(codes);offset=(count+1)*4;offsets=[]
 for shape in shapes:offsets.append(offset);offset+=len(shape)
 body=struct.pack('<HBBB',30000,0x8c,0,len(name))+name+struct.pack('<H',count)
 body+=b''.join(struct.pack('<I',o) for o in offsets)+struct.pack('<I',offset)+b''.join(shapes)+b''.join(struct.pack('<H',c) for c in codes)
 h=font['hhea'];body+=struct.pack('<hhh',round(h.ascent*scale),round(-h.descent*scale),round(h.lineGap*scale))+b''.join(struct.pack('<h',a) for a in adv)+b''.join(bounds)+struct.pack('<H',0)
 raw=swf.read_bytes();raw=raw if raw[:3]==b'FWS' else b'FWS'+raw[3:8]+zlib.decompress(raw[8:]);pos=8+(5+(raw[8]>>3)*4+7)//8+4
 raw=raw[:pos]+tag(75,body)+raw[pos:];raw=raw[:4]+struct.pack('<I',len(raw))+raw[8:];swf.write_bytes(raw)
 return count
if __name__=='__main__':
 import sys
 print('Embedded glyphs:',embed(Path(sys.argv[1]),Path(sys.argv[2])))
