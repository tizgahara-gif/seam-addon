# Auto Seam UV Equalizer

## Overview

Auto Seam UV Equalizer is a Blender 4.x add-on that helps with the initial UV setup pass for mesh objects. It automatically marks seams from face-angle changes, material boundaries, open boundary edges, non-manifold edges, and an optional longitudinal helper for cylindrical or cable-like forms. It can then unwrap, average UV island scale, apply simple material-based UV island scaling, and pack islands into the 0-1 UV space.

This add-on is intended to reduce repetitive setup work for VRC accessories, hard-surface props, supports, panels, pipes, cables, and mixed small parts. It does not guarantee final production-ready UV layouts.

## v0.2 Features

- Longitudinal seam helper for cylinders, pipes, supports, and cable-like meshes.
- Better error reporting during unwrap.
- Shared mesh datablock processing option.
- Material-based UV scale rule input.
- Clearer zip installation instructions.

## Installation

1. Zip the `auto_seam_uv_equalizer` folder itself.
2. In Blender, open **Edit > Preferences > Add-ons**.
3. Click **Install** and choose the zip file.
4. Enable **Auto Seam UV Equalizer**.
5. Open the 3D View sidebar with **N**, then use the **Auto UV** tab.

### Correct Zip Structure

Do not install a zip of the entire GitHub repository directly into Blender. Zip the add-on folder itself so `__init__.py` is one level under `auto_seam_uv_equalizer/`.

Correct:

```text
auto_seam_uv_equalizer.zip
└─ auto_seam_uv_equalizer/
   ├─ __init__.py
   ├─ properties.py
   ├─ operators.py
   ├─ ui.py
   ├─ seam_detection.py
   ├─ uv_tools.py
   ├─ island_tools.py
   └─ README.md
```

Incorrect:

```text
seam-addon-main.zip
└─ seam-addon-main/
   └─ auto_seam_uv_equalizer/
      ├─ __init__.py
      └─ ...
```

## Usage

1. Select one or more mesh objects to unwrap.
2. Open the 3D View sidebar with **N**.
3. Go to **Auto UV > Auto Seam UV**.
4. Adjust **Angle Threshold (Degrees)**, **UV Margin**, seam detection options, and processing options.
5. Click one of the action buttons:
   - **Auto Mark Seams Only**: only marks automatic seams.
   - **Auto Unwrap Only**: unwraps using the current seams.
   - **Auto Seam + Unwrap**: marks seams, optionally adds a longitudinal helper seam, unwraps, averages island scale, applies material UV scale rules, and packs islands.
   - **Clear Seams**: removes seam marks from selected mesh objects.

## Settings

### Seam Detection

- **Angle Threshold (Degrees)**: Marks an edge as a seam when the angle between the two adjacent face normals is at least this many degrees. This value is stored and processed as degrees; the add-on converts it to radians internally for comparison.
- **Clear Existing Seams**: Removes current seams before automatic seam detection.
- **Mark Material Boundaries**: Marks edges between faces with different material indices.
- **Mark Boundary Edges**: Marks open mesh boundary edges.
- **Mark Non-Manifold Edges**: Marks edges connected to three or more faces.
- **Mark Longitudinal Seam Helper**: Heuristically adds one lengthwise seam strip for cylinders, pipes, supports, and cable-like meshes where angle detection alone may only mark cap boundaries.

### UV Settings

- **UV Map Name**: Name of the UV map to use or create. The default is `UV_Auto`.
- **Create UV If Missing**: Creates the named UV map when it does not exist.
- **Unwrap Method**: Chooses Blender's `ANGLE_BASED` or `CONFORMAL` unwrap method.
- **UV Margin**: Margin used by unwrap and pack operations.
- **Average Island Scale**: Runs Blender's average island scale operation after unwrap.
- **Material UV Scale Rules**: Comma-separated `MaterialName=Scale` rules applied after unwrap and average island scale, before packing. Example: `MAT_BluePanel=1.5,MAT_RedMetal=1.0,MAT_Cable=0.6`.
- **Pack Islands**: Packs islands into the 0-1 UV space after unwrap and material scaling.

### Processing

- **Process Shared Mesh Data Once**: When enabled, if multiple selected objects use the same mesh datablock, only the first object is processed and later shared users are skipped. The add-on reports skipped objects. When disabled, every selected object is processed, but shared mesh datablocks still produce a warning.

## Material UV Scale Rules

Material scale rules are a simple way to make important material regions larger or less important regions smaller before final packing.

Rules use this format:

```text
MaterialName=Scale,MaterialName=Scale
```

Examples:

```text
MAT_BluePanel=1.5,MAT_RedMetal=1.0,MAT_Cable=0.6
```

Invalid items are ignored and reported as warnings. For example, `MAT_A=abc,MAT_B=1.2,BadRule` keeps `MAT_B=1.2`, warns about `MAT_A=abc`, warns about `BadRule`, and continues without crashing.

The implementation uses seam-delimited face islands, chooses each island's representative material by the largest accumulated polygon area, and scales that island around its UV center. Inspect the result after packing because mixed-material islands or unusual seam layouts may need manual cleanup.

## Recommended Settings

- **Hard Surface**: Angle Threshold 45-55.
- **Soft Surface**: Angle Threshold 60-75.
- **Material ID workflow**: Keep **Mark Material Boundaries** enabled.
- **Open meshes**: Keep **Mark Boundary Edges** enabled.
- **Cylinders / Pipes / Cables**: Enable **Mark Longitudinal Seam Helper** when the side surface needs a lengthwise seam.
- **Shared mesh users**: Keep **Process Shared Mesh Data Once** enabled unless you intentionally want to run operators once per object selection.

## Known Limitations

- Longitudinal seam helper is heuristic, not a perfect cylinder detector.
- Important faces may still require manual UV editing.
- Material UV scale rules may require manual repacking and inspection.
- This add-on reduces UV setup labor but does not guarantee final production-ready UVs.
- It does not choose aesthetically hidden seam locations for faces, characters, or hero surfaces.
- It does not automatically detect every important panel or every cable; use material names and manual cleanup where needed.
- It does not rectangle-align islands, straighten strips, support UDIMs, export to Substance Painter, or perform advanced overlap detection.
- Cylinders usually get seams around cap boundaries from angle detection, but a vertical side seam may not be created by angle alone. Enable **Mark Longitudinal Seam Helper** or add a side seam manually when the cylinder needs to unfold as a rectangular strip.
- The add-on does not apply object scale. Non-uniform scale can affect perceived texel density, so review UVs manually when objects are scaled unevenly.
- If multiple selected objects share the same mesh datablock, seam and UV changes affect all users of that mesh. The add-on can skip duplicate shared users, but it does not make single-user copies automatically.

## Manual Adjustment Cases

Manual cleanup is expected when the model has:

- Hero faces or visible panels that need deliberately larger UV island area.
- Character faces or surfaces where seams must be hidden from view.
- Cylinders, cables, pipes, or straps requiring a specific longitudinal seam location.
- Long strips that need straightening or rectangular alignment.
- Mixed-material islands where the representative material rule is not enough.
- Material painting workflows that require specific island grouping or padding beyond a simple automatic pack.

## Test Suggestions

- **Cube**: Use the default 55 degree threshold. Edges should be marked as seams and the mesh should unwrap without crashing.
- **Cylinder**: Compare with **Mark Longitudinal Seam Helper** off and on. With it on, the side should receive an additional lengthwise seam candidate.
- **Cable-like converted mesh**: Enable the longitudinal helper and confirm it adds a limited lengthwise seam strip instead of cutting all edges.
- **Material Split Cube**: Enable and disable **Mark Material Boundaries** and confirm material boundary seams change.
- **Shared Mesh Data**: Select multiple objects that share one mesh datablock. With **Process Shared Mesh Data Once** on, only the first is processed and later users are reported as skipped.
- **Invalid Material UV Scale Rules**: Try `MAT_A=abc,MAT_B=1.2,BadRule`; invalid entries should warn while the valid entry remains active.

## Example Workflow

1. Finish the model in Blender.
2. Assign color/material IDs if needed for a Substance Painter mask workflow.
3. Enable **Mark Longitudinal Seam Helper** for pipes, supports, or cable-heavy meshes if needed.
4. Optionally set **Material UV Scale Rules** such as `MAT_BluePanel=1.5,MAT_Cable=0.6`.
5. Run **Auto Seam + Unwrap**.
6. Open the UV Editor and manually adjust important islands.
7. Repack or fine-tune islands as needed.
8. Export to your target pipeline.
