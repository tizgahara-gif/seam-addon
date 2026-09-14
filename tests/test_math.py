import importlib.util
from pathlib import Path
ROOT=Path(__file__).parents[1]/'auto_seam_uv_equalizer'
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/f'{name}.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
sym=load('symmetry'); td=load('texel_density'); val=load('uv_validation')
def test_mirror_unique_and_asymmetric_skip():
 coords=[(1,0,0),(-1,0,0),(1,1,0),(-1,1,0),(3,0,0)]
 mapping,skipped=sym.mirror_edge_map(coords,[(0,2),(1,3),(0,4)],0,1e-5)
 assert mapping[0]==1 and mapping[1]==0 and skipped>=1
def test_center_edge_maps_to_itself():
 mapping,skipped=sym.mirror_edge_map([(0,-1,0),(0,1,0)],[(0,1)],0,1e-5)
 assert mapping=={0:0} and skipped==0
def test_non_square_density_uses_both_dimensions():
 assert td.density_from_areas(2,2048*1024)==(2048*1024/2)**.5
 assert td.density_from_areas(1,10000,'PX_CM')==1
def test_signed_uv_area():
 assert val.signed_area((0,0),(1,0),(0,1))>.0
 assert val.signed_area((0,0),(0,1),(1,0))<.0
