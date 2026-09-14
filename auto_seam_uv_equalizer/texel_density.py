"""Pure texel-density math and Blender mesh adapters."""
from __future__ import annotations
from math import sqrt

def density_from_areas(world_area, uv_pixel_area, unit="PX_M"):
    if world_area <= 0.0 or uv_pixel_area <= 0.0: return 0.0
    value = sqrt(uv_pixel_area / world_area)
    return value / 100.0 if unit == "PX_CM" else value

def scale_for_density(current, target): return target / current if current > 0.0 else 1.0

def measure_object(obj, width, height, unit="PX_M"):
    mesh=obj.data; uv=mesh.uv_layers.active
    if uv is None: raise RuntimeError("Active UV map required")
    mesh.calc_loop_triangles(); world_area=uv_area=0.0
    for tri in mesh.loop_triangles:
        a,b,c=(obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices)
        world_area += (b-a).cross(c-a).length * .5
        p=[uv.uv[i].vector for i in tri.loops]
        uv_area += abs((p[1].x-p[0].x)*(p[2].y-p[0].y)-(p[1].y-p[0].y)*(p[2].x-p[0].x))*.5*width*height
    return density_from_areas(world_area, uv_area, unit)
