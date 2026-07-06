import atexit
import threading
import numpy as np
from aerogen.constants import TUNNEL_H
from aerogen.geometry import get_bezier_x_coords, normalize_y_params
_gmsh_ready = False
_mesh_lock = threading.Lock()

def init_gmsh():
    global _gmsh_ready
    if _gmsh_ready:
        return
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber('General.Terminal', 0)
    _gmsh_ready = True

def shutdown_gmsh():
    global _gmsh_ready
    if not _gmsh_ready:
        return
    import gmsh
    gmsh.finalize()
    _gmsh_ready = False
atexit.register(shutdown_gmsh)

def generate_mesh(mode, y_params, lc=0.08):
    import gmsh
    with _mesh_lock:
        init_gmsh()
        gmsh.clear()
        gmsh.model.add('diffuser_domain')
        y_cp = normalize_y_params(mode, y_params)
        x_cp = get_bezier_x_coords(mode)
        lc_coarse = lc
        lc_fine = lc * 0.4
        p1 = gmsh.model.geo.addPoint(0.0, 0.0, 0.0, lc_coarse)
        p2 = gmsh.model.geo.addPoint(1.5, 0.0, 0.0, lc_coarse)
        bezier_point_tags = [gmsh.model.geo.addPoint(float(xv), float(yv), 0.0, lc_fine) for xv, yv in zip(x_cp, y_cp)]
        p5 = gmsh.model.geo.addPoint(3.5, 0.0, 0.0, lc_coarse)
        p6 = gmsh.model.geo.addPoint(5.0, 0.0, 0.0, lc_coarse)
        p7 = gmsh.model.geo.addPoint(5.0, TUNNEL_H, 0.0, lc_coarse)
        p8 = gmsh.model.geo.addPoint(0.0, TUNNEL_H, 0.0, lc_coarse)
        l1 = gmsh.model.geo.addLine(p1, p2)
        l2 = gmsh.model.geo.addLine(p2, bezier_point_tags[0])
        l_bezier = gmsh.model.geo.addBezier(bezier_point_tags)
        l4 = gmsh.model.geo.addLine(bezier_point_tags[-1], p5)
        l5 = gmsh.model.geo.addLine(p5, p6)
        l6 = gmsh.model.geo.addLine(p6, p7)
        l7 = gmsh.model.geo.addLine(p7, p8)
        l8 = gmsh.model.geo.addLine(p8, p1)
        loop = gmsh.model.geo.addCurveLoop([l1, l2, l_bezier, l4, l5, l6, l7, l8])
        surf = gmsh.model.geo.addPlaneSurface([loop])
        gmsh.model.geo.synchronize()
        gmsh.model.addPhysicalGroup(1, [l8], name='Inlet')
        gmsh.model.addPhysicalGroup(1, [l6], name='Outlet')
        gmsh.model.addPhysicalGroup(1, [l7], name='Ceiling')
        gmsh.model.addPhysicalGroup(1, [l1, l2, l_bezier, l4, l5], name='Floor')
        gmsh.model.addPhysicalGroup(2, [surf], name='Domain')
        gmsh.model.mesh.generate(2)
        node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
        nodes_x = node_coords[0::3]
        nodes_y = node_coords[1::3]
        max_tag = int(np.max(node_tags))
        tag_to_index = np.zeros(max_tag + 1, dtype=int)
        tag_to_index[node_tags] = np.arange(len(node_tags))
        elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(2)
        elements = []
        for el_type, el_tags, nd_tags in zip(elem_types, elem_tags, elem_node_tags):
            if el_type == 2:
                elements = nd_tags.reshape(-1, 3)
                break
        elements = tag_to_index[elements]
        boundary_elements = {}
        for dim, group_tag in gmsh.model.getPhysicalGroups(1):
            group_name = gmsh.model.getPhysicalName(dim, group_tag)
            entities = gmsh.model.getEntitiesForPhysicalGroup(dim, group_tag)
            group_lines = []
            for entity in entities:
                el_types, el_tags, nd_tags = gmsh.model.mesh.getElements(dim, entity)
                for el_type, el_tags, nd_tags in zip(el_types, el_tags, nd_tags):
                    if el_type == 1:
                        group_lines.append(nd_tags.reshape(-1, 2))
            if group_lines:
                boundary_elements[group_name] = tag_to_index[np.concatenate(group_lines, axis=0)]
        return (nodes_x, nodes_y, elements, boundary_elements)
