"""Persistent seam groups stored as compact mesh custom properties."""
PREFIX="autoseam_group_"
def save(mesh,name): mesh[PREFIX+name]=[e.index for e in mesh.edges if e.use_seam]
def apply(mesh,name,merge=False):
    key=PREFIX+name
    if key not in mesh: raise KeyError(name)
    saved=set(mesh[key])
    for edge in mesh.edges: edge.use_seam=(edge.use_seam if merge else False) or edge.index in saved
    mesh.update()
def delete(mesh,name):
    key=PREFIX+name
    if key in mesh: del mesh[key]
