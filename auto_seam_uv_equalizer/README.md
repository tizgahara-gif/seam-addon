# Auto Seam UV Equalizer

## Overview

Auto Seam UV Equalizer is a Blender 4.x add-on that helps with the initial UV setup pass for mesh objects. It automatically marks seams from face-angle changes, material boundaries, open boundary edges, and non-manifold edges, then can unwrap, average UV island scale, and pack islands into the 0-1 UV space.

This add-on is intended to reduce repetitive setup work. It does not guarantee final production-ready UV layouts.

## Installation

1. Zip the `auto_seam_uv_equalizer` folder.
2. In Blender, open **Edit > Preferences > Add-ons**.
3. Click **Install** and choose the zip file.
4. Enable **Auto Seam UV Equalizer**.
5. Open the 3D View sidebar with **N**, then use the **Auto UV** tab.

## Usage

1. Select one or more mesh objects to unwrap.
2. Open the 3D View sidebar with **N**.
3. Go to **Auto UV > Auto Seam UV**.
4. Adjust **Angle Threshold**, **UV Margin**, and detection options.
5. Click one of the action buttons:
   - **Auto Mark Seams Only**: only marks automatic seams.
   - **Auto Unwrap Only**: unwraps using the current seams.
   - **Auto Seam + Unwrap**: marks seams, unwraps, averages island scale, and packs islands.
   - **Clear Seams**: removes seam marks from selected mesh objects.

## Settings

### Seam Detection

- **Angle Threshold**: Marks an edge as a seam when the angle between the two adjacent face normals is at least this many degrees.
- **Clear Existing Seams**: Removes current seams before automatic seam detection.
- **Mark Material Boundaries**: Marks edges between faces with different material indices.
- **Mark Boundary Edges**: Marks open mesh boundary edges.
- **Mark Non-Manifold Edges**: Marks edges connected to three or more faces.

### UV Settings

- **UV Map Name**: Name of the UV map to use or create. The default is `UV_Auto`.
- **Create UV If Missing**: Creates the named UV map when it does not exist.
- **Unwrap Method**: Chooses Blender's `ANGLE_BASED` or `CONFORMAL` unwrap method.
- **UV Margin**: Margin used by unwrap and pack operations.
- **Average Island Scale**: Runs Blender's average island scale operation after unwrap.
- **Pack Islands**: Packs islands into the 0-1 UV space after unwrap.

## Recommended Settings

- **Hard Surface**: Angle Threshold 45-55.
- **Soft Surface**: Angle Threshold 60-75.
- **Material ID workflow**: Keep **Mark Material Boundaries** enabled.
- **Open meshes**: Keep **Mark Boundary Edges** enabled.

## Known Limitations

- This is an initial UV layout assistant, not a final UV layout generator.
- It does not choose aesthetically hidden seam locations for faces, characters, or hero surfaces.
- It does not automatically enlarge important UV islands such as colored panels or main visible faces.
- It does not rectangle-align islands, straighten strips, support UDIMs, export to Substance Painter, or perform advanced overlap detection.
- Cylinders usually get seams around cap boundaries from angle detection, but a vertical side seam may not be created by angle alone because neighboring side faces can be below the threshold or smooth in practice. Add or adjust a side seam manually when the cylinder needs to unfold as a rectangular strip.
- The add-on does not apply object scale. Non-uniform scale can affect perceived texel density, so review UVs manually when objects are scaled unevenly.
- If multiple selected objects share the same mesh datablock, seam and UV changes affect all users of that mesh. The add-on reports a warning but does not make single-user copies automatically.

## Manual Adjustment Cases

Manual cleanup is expected when the model has:

- Hero faces or visible panels that need larger UV island area.
- Character faces or surfaces where seams must be hidden from view.
- Cylinders, cables, pipes, or straps requiring a deliberate longitudinal seam.
- Long strips that need straightening or rectangular alignment.
- Material painting workflows that require specific island grouping or padding beyond a simple automatic pack.

## Example Workflow

1. Finish the model in Blender.
2. Assign color/material IDs if needed for a Substance Painter mask workflow.
3. Run **Auto Seam + Unwrap**.
4. Open the UV Editor and manually adjust important islands.
5. Repack or fine-tune islands as needed.
6. Export to your target pipeline.
