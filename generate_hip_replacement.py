"""
Total Hip Replacement Load Transfer Analysis Generator
Patient-Specific FEA with Acetabular and Femoral Components

Author: Jeffrey Husch, Senior Biomedical Engineer
Application: ParaView Orthopedic FEA - Load Path Visualization
"""
import math
import os

# ============================================================================
# HIGH-RESOLUTION GRID PARAMETERS
# ============================================================================
nx, ny, nz = 50, 50, 120
spacing = 1.0  # mm
origin = (-25, -25, -20)

# ============================================================================
# ANATOMICAL PARAMETERS
# ============================================================================

# Proximal femur geometry
FEMUR_SHAFT_RADIUS = 16  # mm
FEMUR_HEAD_RADIUS = 26   # mm
FEMORAL_NECK_ANGLE = 125 # degrees
CORTICAL_THICKNESS = 4.5 # mm
CANAL_RADIUS = 8         # mm medullary canal

# Acetabulum geometry
ACETABULUM_RADIUS = 28   # mm
ACETABULUM_DEPTH = 22    # mm
SUBCHONDRAL_THICKNESS = 2 # mm

# Implant geometry
STEM_LENGTH = 90         # mm
STEM_PROXIMAL_WIDTH = 14 # mm
STEM_DISTAL_WIDTH = 5    # mm
CUP_OUTER_RADIUS = 27    # mm
CUP_INNER_RADIUS = 14    # mm (for femoral head)
LINER_THICKNESS = 6      # mm (UHMWPE)

# Material properties (MPa)
MATERIALS = {
    'cortical_bone': {'E': 17000, 'nu': 0.3, 'yield': 120},
    'cancellous_bone': {'E': 500, 'nu': 0.3, 'yield': 5},
    'titanium': {'E': 110000, 'nu': 0.34, 'yield': 900},
    'cobalt_chrome': {'E': 210000, 'nu': 0.30, 'yield': 500},
    'uhmwpe': {'E': 1000, 'nu': 0.46, 'yield': 25},
    'pmma': {'E': 2500, 'nu': 0.38, 'yield': 80}
}

# Loading (ISO 7206 walking cycle)
BODY_WEIGHT = 800        # N (80 kg)
LOAD_MULTIPLIER = 3.0    # Peak stance phase
RESULTANT_LOAD = BODY_WEIGHT * LOAD_MULTIPLIER  # 2400 N
LOAD_ANGLE = 16          # degrees from vertical (abductor angle)

def calculate_load_vector():
    """Calculate hip joint reaction force vector."""
    angle_rad = math.radians(LOAD_ANGLE)
    Fx = RESULTANT_LOAD * math.sin(angle_rad)  # Medial-lateral
    Fy = 0  # Anterior-posterior (simplified)
    Fz = -RESULTANT_LOAD * math.cos(angle_rad)  # Superior-inferior (compression)
    return Fx, Fy, Fz

def distance_3d(x, y, z, cx, cy, cz):
    return math.sqrt((x-cx)**2 + (y-cy)**2 + (z-cz)**2)

def femur_with_canal(x, y, z):
    """
    Define femoral geometry with reamed canal for stem.
    Returns: (tissue_type, in_bone)
    0=outside, 1=cortical, 2=cancellous, 3=canal
    """
    # Shaft region (z < 50)
    if z < 50:
        r = math.sqrt(x**2 + y**2)
        if r < CANAL_RADIUS:
            return 3, False  # Reamed canal (for stem)
        elif r < FEMUR_SHAFT_RADIUS - CORTICAL_THICKNESS:
            return 2, True   # Cancellous
        elif r < FEMUR_SHAFT_RADIUS:
            return 1, True   # Cortical
        return 0, False
    
    # Metaphyseal region (50 <= z < 75)
    elif z < 75:
        progress = (z - 50) / 25
        shaft_expansion = 1 + progress * 0.4  # Flares proximally
        current_radius = FEMUR_SHAFT_RADIUS * shaft_expansion
        
        r = math.sqrt(x**2 + y**2)
        canal_r = CANAL_RADIUS * (1 + progress * 0.6)  # Canal also expands
        
        if r < canal_r:
            return 3, False
        elif r < current_radius - CORTICAL_THICKNESS * 0.7:
            return 2, True
        elif r < current_radius:
            return 1, True
        return 0, False
    
    # Neck and head region (z >= 75)
    else:
        # Femoral neck (angled)
        neck_progress = (z - 75) / 20
        neck_center_x = neck_progress * 20  # Lateral offset
        neck_center_y = 0
        neck_radius = 12 - neck_progress * 3
        
        r_neck = math.sqrt((x - neck_center_x)**2 + y**2)
        
        # Head (z > 90)
        if z > 90:
            head_center = (22, 0, 95)
            r_head = distance_3d(x, y, z, *head_center)
            
            if r_head < FEMUR_HEAD_RADIUS - 4:
                return 2, True  # Cancellous head
            elif r_head < FEMUR_HEAD_RADIUS:
                return 1, True  # Subchondral plate
            # Check if in neck
            elif r_neck < neck_radius:
                return 2, True
            return 0, False
        
        # Neck only
        if r_neck < neck_radius - 2:
            return 2, True
        elif r_neck < neck_radius:
            return 1, True
        
        # Greater trochanter
        if x > 10 and z < 85:
            gt_center = (18, 0, 78)
            r_gt = distance_3d(x, y, z, *gt_center)
            if r_gt < 12:
                return 1, True
        
        return 0, False

def acetabulum_geometry(x, y, z):
    """
    Define acetabular (pelvic) bone geometry.
    Returns: (tissue_type, in_bone)
    """
    # Acetabulum is superior, centered around (15, 0, 100)
    cup_center = (15, 0, 100)
    r = distance_3d(x, y, z, *cup_center)
    
    if z < 95:  # Below acetabulum
        return 0, False
    
    # Hemispherical acetabulum
    if r < ACETABULUM_RADIUS:
        if r > ACETABULUM_RADIUS - SUBCHONDRAL_THICKNESS:
            return 1, True  # Subchondral bone
        elif r > ACETABULUM_RADIUS - 8:
            return 2, True  # Cancellous
        return 0, False  # Cup cavity
    
    # Surrounding pelvis
    if z > 95 and abs(x - 15) < 30 and abs(y) < 20:
        return 2, True  # Simplified pelvic cancellous
    
    return 0, False

def implant_stem(x, y, z):
    """
    Define femoral stem geometry (cemented or press-fit).
    Returns: (component_type, in_implant)
    1=stem, 2=neck, 3=head, 4=cement
    """
    # Stem body (0 < z < 90)
    if 0 < z < 90:
        stem_progress = z / STEM_LENGTH
        # Tapered stem width
        width_factor = 1 - (stem_progress * 0.6)  # Tapers distally
        current_half_width = (STEM_PROXIMAL_WIDTH / 2) * width_factor
        
        r = math.sqrt(x**2 + y**2)
        
        # Rectangular cross-section approximation (rounded)
        in_stem = abs(x) < current_half_width and abs(y) < current_half_width * 0.8
        
        if in_stem and r < CANAL_RADIUS - 0.5:
            return 1, True  # Stem body
        elif r < CANAL_RADIUS and z > 5:
            # Check if cement layer (between stem and bone)
            if not in_stem:
                return 4, True  # PMMA cement
    
    # Neck (z 75-95)
    if 75 < z < 95:
        neck_progress = (z - 75) / 20
        neck_center_x = neck_progress * 18
        
        r_neck = math.sqrt((x - neck_center_x)**2 + y**2)
        if r_neck < 6:
            return 2, True  # Stem neck (Ti alloy)
    
    # Femoral head (z > 90)
    if z > 90:
        head_center = (20, 0, 95)
        r_head = distance_3d(x, y, z, *head_center)
        if r_head < 14:  # Prosthetic head radius
            return 3, True  # CoCr head
    
    return 0, False

def acetabular_cup(x, y, z):
    """
    Define acetabular cup and liner.
    Returns: (component_type, in_implant)
    5=cup_shell, 6=liner
    """
    cup_center = (15, 0, 100)
    r = distance_3d(x, y, z, *cup_center)
    
    if z < 95:
        return 0, False
    
    # UHMWPE liner (inner)
    if CUP_INNER_RADIUS < r < CUP_INNER_RADIUS + LINER_THICKNESS:
        # Check if within hemisphere
        dz = z - cup_center[2]
        if dz > -LINER_THICKNESS:
            return 6, True  # Liner
    
    # Metal shell (outer)
    if CUP_INNER_RADIUS + LINER_THICKNESS < r < CUP_OUTER_RADIUS:
        dz = z - cup_center[2]
        if dz > -2:
            return 5, True  # Titanium shell
    
    return 0, False

def calculate_load_transfer(x, y, z, is_femur, is_pelvis, is_implant, component):
    """
    Calculate stress distribution based on load transfer paths.
    Models load flow from acetabulum through implant to femur.
    """
    Fx, Fy, Fz = calculate_load_vector()
    
    # Joint center (where load is applied)
    joint_center = (18, 0, 95)
    
    # Distance from joint center (load application point)
    dx = x - joint_center[0]
    dy = y - joint_center[1]
    dz = z - joint_center[2]
    
    r_joint = math.sqrt(dx**2 + dy**2 + dz**2)
    r_xy = math.sqrt(x**2 + y**2)
    
    if not (is_femur or is_pelvis or is_implant):
        return 0, 0, 0, 0, (0, 0, 0)
    
    # Load transfer path factor (intensity decreases with distance)
    load_path_factor = 1.0 / (1 + 0.02 * r_joint)
    
    # Axial stress component
    if is_femur:
        # Cross-sectional area (approximate)
        area = math.pi * (FEMUR_SHAFT_RADIUS**2 - CANAL_RADIUS**2)
        axial_stress = abs(Fz) / area * load_path_factor * 1000  # Scale
        
        # Bending stress (from offset loading)
        bending_moment = abs(Fx) * abs(dz)
        I = math.pi * (FEMUR_SHAFT_RADIUS**4 - CANAL_RADIUS**4) / 4
        bending_stress = bending_moment * r_xy / I * 500 if I > 0 else 0
        
    elif is_implant:
        # Implant carries more load due to higher stiffness
        if component in [1, 2]:  # Stem/neck
            E_ratio = MATERIALS['titanium']['E'] / MATERIALS['cortical_bone']['E']
        elif component == 3:  # Head
            E_ratio = MATERIALS['cobalt_chrome']['E'] / MATERIALS['cortical_bone']['E']
        elif component == 6:  # Liner
            E_ratio = MATERIALS['uhmwpe']['E'] / MATERIALS['cortical_bone']['E']
        else:
            E_ratio = 1.0
        
        area = math.pi * 10**2  # Approximate stem cross-section
        axial_stress = abs(Fz) / area * load_path_factor * E_ratio * 50
        bending_stress = abs(dx) * abs(Fz) / 10000
        
    elif is_pelvis:
        # Acetabular stresses
        area = math.pi * ACETABULUM_RADIUS**2 / 2
        axial_stress = abs(Fz) / area * load_path_factor * 500
        bending_stress = 0
    else:
        axial_stress = 0
        bending_stress = 0
    
    # Combine stresses
    von_mises = math.sqrt(axial_stress**2 + 3*bending_stress**2)
    
    # Principal stresses
    sigma_1 = axial_stress + bending_stress
    sigma_3 = -0.3 * axial_stress
    
    # Hydrostatic
    hydrostatic = (sigma_1 + sigma_3) / 3
    
    # Displacement (simplified)
    if is_femur or is_implant:
        E = MATERIALS['titanium']['E'] if is_implant else MATERIALS['cortical_bone']['E']
        disp_z = -von_mises / E * 0.2 * (1 - z/100)
        disp_x = -Fx / E * 0.001 * (z / 50)
        disp_y = 0
    else:
        disp_x, disp_y, disp_z = 0, 0, 0
    
    return von_mises, sigma_1, sigma_3, hydrostatic, (disp_x, disp_y, disp_z)

def write_vtk_grid(filename, data, title):
    """Write VTK structured points file."""
    with open(filename, 'w') as f:
        f.write("# vtk DataFile Version 3.0\n")
        f.write(f"{title}\n")
        f.write("ASCII\nDATASET STRUCTURED_POINTS\n")
        f.write(f"DIMENSIONS {nx} {ny} {nz}\n")
        f.write(f"ORIGIN {origin[0]} {origin[1]} {origin[2]}\n")
        f.write(f"SPACING {spacing} {spacing} {spacing}\n")
        f.write(f"POINT_DATA {nx*ny*nz}\n")
        
        for name, values in data.items():
            if name == "Displacement":
                f.write(f"VECTORS {name} float\n")
                for v in values:
                    f.write(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            else:
                f.write(f"SCALARS {name} float\nLOOKUP_TABLE default\n")
                for v in values:
                    f.write(f"{v:.6f}\n")

# ============================================================================
# GENERATE FEMORAL COMPONENT
# ============================================================================
print("="*60)
print("TOTAL HIP REPLACEMENT - LOAD TRANSFER ANALYSIS")
print("="*60)
print("\nGenerating Femoral Component...")

femur_data = {
    "tissue_type": [], "von_mises_stress": [], "load_transfer_intensity": [],
    "principal_max": [], "principal_min": [], "SED": [],
    "hydrostatic_stress": [], "Displacement": []
}

for k in range(nz):
    z = origin[2] + k * spacing
    for j in range(ny):
        y = origin[1] + j * spacing
        for i in range(nx):
            x = origin[0] + i * spacing
            
            tissue, in_bone = femur_with_canal(x, y, z)
            
            if in_bone:
                E = MATERIALS['cortical_bone']['E'] if tissue == 1 else MATERIALS['cancellous_bone']['E']
                vm, s1, s3, hyd, disp = calculate_load_transfer(x, y, z, True, False, False, 0)
                sed = (vm**2) / (2*E) if E > 0 else 0
                
                # Load transfer intensity (relative to peak)
                load_intensity = vm / 100  # Normalized
            else:
                vm, s1, s3, hyd, sed = 0, 0, 0, 0, 0
                load_intensity = 0
                disp = (0, 0, 0)
            
            femur_data["tissue_type"].append(tissue)
            femur_data["von_mises_stress"].append(vm)
            femur_data["load_transfer_intensity"].append(load_intensity)
            femur_data["principal_max"].append(s1)
            femur_data["principal_min"].append(s3)
            femur_data["SED"].append(sed)
            femur_data["hydrostatic_stress"].append(hyd)
            femur_data["Displacement"].append(disp)

write_vtk_grid("femoral_component.vtk", femur_data,
               "Femoral Bone with Implant Cavity - Load Transfer Analysis")
print("  Created: femoral_component.vtk")

# ============================================================================
# GENERATE PROSTHESIS ASSEMBLY
# ============================================================================
print("Generating Prosthesis Assembly...")

prosthesis_data = {
    "component_type": [], "material_id": [], "von_mises_stress": [],
    "safety_factor": [], "contact_stress": [], "E_modulus": [],
    "Displacement": []
}

for k in range(nz):
    z = origin[2] + k * spacing
    for j in range(ny):
        y = origin[1] + j * spacing
        for i in range(nx):
            x = origin[0] + i * spacing
            
            stem_comp, in_stem = implant_stem(x, y, z)
            cup_comp, in_cup = acetabular_cup(x, y, z)
            
            if in_stem:
                component = stem_comp
                if component == 1:  # Stem
                    mat = 'titanium'
                    mat_id = 1
                elif component == 2:  # Neck
                    mat = 'titanium'
                    mat_id = 1
                elif component == 3:  # Head
                    mat = 'cobalt_chrome'
                    mat_id = 2
                else:  # Cement
                    mat = 'pmma'
                    mat_id = 4
            elif in_cup:
                component = cup_comp
                if component == 5:  # Shell
                    mat = 'titanium'
                    mat_id = 1
                else:  # Liner
                    mat = 'uhmwpe'
                    mat_id = 3
            else:
                component = 0
                mat = None
                mat_id = 0
            
            if component > 0:
                E = MATERIALS[mat]['E']
                yield_str = MATERIALS[mat]['yield']
                
                vm, s1, s3, hyd, disp = calculate_load_transfer(x, y, z, False, False, True, component)
                safety = yield_str / max(vm, 0.1)
                
                # Contact stress at articulating surface
                joint_center = (18, 0, 95)
                r_joint = distance_3d(x, y, z, *joint_center)
                if 13 < r_joint < 15 and component == 3:  # Head-liner interface
                    contact = vm * 1.5
                else:
                    contact = 0
            else:
                E = 0
                vm, safety, contact = 0, 0, 0
                disp = (0, 0, 0)
            
            prosthesis_data["component_type"].append(component)
            prosthesis_data["material_id"].append(mat_id)
            prosthesis_data["von_mises_stress"].append(vm)
            prosthesis_data["safety_factor"].append(min(safety, 10))
            prosthesis_data["contact_stress"].append(contact)
            prosthesis_data["E_modulus"].append(E)
            prosthesis_data["Displacement"].append(disp)

write_vtk_grid("prosthesis_assembly.vtk", prosthesis_data,
               "Hip Prosthesis Assembly - Stem, Head, Cup, Liner")
print("  Created: prosthesis_assembly.vtk")

# ============================================================================
# GENERATE PELVIC ACETABULAR COMPONENT
# ============================================================================
print("Generating Pelvic Component...")

pelvis_data = {
    "tissue_type": [], "von_mises_stress": [], "bone_quality": [],
    "cup_support": [], "Displacement": []
}

for k in range(nz):
    z = origin[2] + k * spacing
    for j in range(ny):
        y = origin[1] + j * spacing
        for i in range(nx):
            x = origin[0] + i * spacing
            
            tissue, in_bone = acetabulum_geometry(x, y, z)
            
            if in_bone:
                vm, s1, s3, hyd, disp = calculate_load_transfer(x, y, z, False, True, False, 0)
                
                # Bone quality (1=good, 0=poor - osteoporotic)
                quality = 1.0 - (z - 95) * 0.02 if z > 95 else 1.0
                
                # Cup support index (how well bone supports cup)
                cup_center = (15, 0, 100)
                r_cup = distance_3d(x, y, z, *cup_center)
                cup_support = max(0, 1 - abs(r_cup - ACETABULUM_RADIUS) / 5) if tissue == 1 else 0
            else:
                vm = 0
                quality = 0
                cup_support = 0
                disp = (0, 0, 0)
            
            pelvis_data["tissue_type"].append(tissue)
            pelvis_data["von_mises_stress"].append(vm)
            pelvis_data["bone_quality"].append(quality)
            pelvis_data["cup_support"].append(cup_support)
            pelvis_data["Displacement"].append(disp)

write_vtk_grid("pelvic_component.vtk", pelvis_data,
               "Pelvic Acetabulum - Cup Support Analysis")
print("  Created: pelvic_component.vtk")

# ============================================================================
# GENERATE MULTI-BLOCK VTM FILE
# ============================================================================
print("Generating Multi-Block Assembly...")

vtm_content = '''<?xml version="1.0"?>
<VTKFile type="vtkMultiBlockDataSet" version="1.0" byte_order="LittleEndian">
  <vtkMultiBlockDataSet>
    <Block index="0" name="Femoral_Bone">
      <DataSet index="0" file="femoral_component.vtk"/>
    </Block>
    <Block index="1" name="Prosthesis_Assembly">
      <DataSet index="0" file="prosthesis_assembly.vtk"/>
    </Block>
    <Block index="2" name="Pelvic_Acetabulum">
      <DataSet index="0" file="pelvic_component.vtk"/>
    </Block>
  </vtkMultiBlockDataSet>
</VTKFile>
'''

with open("total_hip_replacement.vtm", "w") as f:
    f.write(vtm_content)
print("  Created: total_hip_replacement.vtm")

# ============================================================================
# STATISTICS
# ============================================================================
print("\n" + "="*60)
print("GENERATION COMPLETE")
print("="*60)
print(f"Grid: {nx} x {ny} x {nz} = {nx*ny*nz:,} points per block")
print(f"Total: {nx*ny*nz*3:,} data points (3 blocks)")
print(f"Loading: {RESULTANT_LOAD:.0f} N at {LOAD_ANGLE}° (ISO 7206)")
print("\nFiles:")
print("  - total_hip_replacement.vtm (Multi-Block)")
print("  - femoral_component.vtk")
print("  - prosthesis_assembly.vtk")
print("  - pelvic_component.vtk")
