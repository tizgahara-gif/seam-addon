"""UV validation based on Blender's loop-triangle tessellation."""
from __future__ import annotations
from math import sqrt

def signed_area(a,b,c): return ((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))*.5
def validate_object(obj, tolerance=1e-10, stretch_threshold=2.0):
    mesh=obj.data; uv=mesh.uv_layers.active
    if uv is None: raise RuntimeError("Active UV map required")
    mesh.calc_loop_triangles(); flipped=set(); zero=set(); stretches=[]; uv_area=0.0
    for tri in mesh.loop_triangles:
        points=[uv.data[i].uv for i in tri.loops]; area=signed_area(*points)
        if area < -tolerance: flipped.add(tri.polygon_index)
        if abs(area) <= tolerance or any((points[i]-points[(i+1)%3]).length_squared <= tolerance for i in range(3)): zero.add(tri.polygon_index)
        a,b,c=(obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices)
        area3=(b-a).cross(c-a).length*.5
        if area3 > tolerance and abs(area)>tolerance:
            ratio=abs(area)/area3; stretches.append(max(ratio,1.0/ratio))
        uv_area += abs(area)
    avg=sum(stretches)/len(stretches) if stretches else 0.0
    return {"flipped":flipped,"zero":zero,"average_stretch":avg,"max_stretch":max(stretches,default=0.0),"problem_count":sum(v>stretch_threshold for v in stretches),"coverage":uv_area}
