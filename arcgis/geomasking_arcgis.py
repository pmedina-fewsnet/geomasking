# -*- coding: utf-8 -*-
"""
Geomasking point displacement engine for ArcGIS Pro.
"""
import os
import random
import pandas as pd
import arcpy


def ingest_villages(table, output_name, workspace):
    """
    Ingests CSV village data using InsertCursor to avoid schema-locking
    and overwrite bugs inherent to XYTableToPoint.
    """
    arcpy.env.overwriteOutput = True
    full_output = os.path.join(workspace, output_name)

    if arcpy.Exists(full_output):
        try:
            arcpy.management.Delete(full_output)
        except Exception:
            pass

    # Read source CSV
    df = pd.read_csv(table)

    sr_wgs84 = arcpy.SpatialReference(4326)
    arcpy.management.CreateFeatureclass(
        out_path=workspace,
        out_name=output_name,
        geometry_type="POINT",
        spatial_reference=sr_wgs84
    )

    # Establish attributes
    arcpy.management.AddField(full_output, "FNID", "TEXT", field_length=100)
    arcpy.management.AddField(full_output, "ADM1ADM2", "TEXT", field_length=200)
    arcpy.management.AddField(full_output, "Latitude", "DOUBLE")
    arcpy.management.AddField(full_output, "Longitude", "DOUBLE")
    arcpy.management.AddField(full_output, "old_Latitude", "DOUBLE")
    arcpy.management.AddField(full_output, "old_Longitude", "DOUBLE")

    fields = ["SHAPE@", "FNID", "ADM1ADM2", "Latitude", "Longitude", "old_Latitude", "old_Longitude"]
    with arcpy.da.InsertCursor(full_output, fields) as cur:
        for _, r in df.iterrows():
            lon_val = float(r["Longitude"])
            lat_val = float(r["Latitude"])
            fnid_val = str(r["FNID"]).strip()
            adm_val = str(r["ADM1ADM2"]).strip() if "ADM1ADM2" in r else ""
            
            pt_geom = arcpy.PointGeometry(arcpy.Point(lon_val, lat_val), sr_wgs84)
            cur.insertRow([pt_geom, fnid_val, adm_val, lat_val, lon_val, lat_val, lon_val])

    return full_output


def ingest_admins(admin_path, workspace, admin1="ADMIN1", admin2="ADMIN2"):
    """
    Exports clean admin boundaries to the workspace, ensuring no existing 
    selections in the ArcGIS Pro active map restrict the exported features.
    """
    arcpy.env.overwriteOutput = True
    out_name = os.path.join(workspace, "Boundaries")

    if arcpy.Exists(out_name):
        try:
            arcpy.management.Delete(out_name)
        except Exception:
            pass

    # Clear any active map-layer selections to prevent partial exports
    if arcpy.Exists(admin_path):
        try:
            arcpy.management.SelectLayerByAttribute(admin_path, "CLEAR_SELECTION")
        except Exception:
            pass

    arcpy.conversion.ExportFeatures(
        in_features=admin_path, 
        out_features=out_name
    )

    arcpy.management.AddField(in_table=out_name, field_name="ADM1ADM2", field_type="TEXT", field_length=200)
    
    with arcpy.da.UpdateCursor(out_name, ["ADM1ADM2", admin1, admin2]) as cursor:
        for row in cursor:
            part1 = str(row[1]).strip() if row[1] is not None else ""
            part2 = str(row[2]).strip() if row[2] is not None else ""
            row[0] = part1 + part2
            cursor.updateRow(row)

    return out_name


def get_new_coordinates(point, boundary, max_dist, min_dist, workspace):
    """
    Computes an annular geodesic displacement buffer, clips to the admin boundary,
    and returns a random candidate coordinate tuple (lat, lon).
    """
    arcpy.env.overwriteOutput = True

    # 1. Generate concentric geodesic buffers (handles metric distances on degree-based data)
    outer_buffer = arcpy.analysis.Buffer(
        in_features=point,
        out_feature_class=os.path.join(workspace, "outer_buffer"),
        buffer_distance_or_field=f"{max_dist} Meters", 
        method="GEODESIC"
    )
    inner_buffer = arcpy.analysis.Buffer(
        in_features=point,
        out_feature_class=os.path.join(workspace, "inner_buffer"),
        buffer_distance_or_field=f"{min_dist} Meters", 
        method="GEODESIC"
    )

    # 2. Symmetric difference produces the donut ring
    buffer_zone = arcpy.analysis.SymDiff(
        in_features=outer_buffer,
        update_features=inner_buffer,
        out_feature_class=os.path.join(workspace, "buffer_zone")
    )

    # 3. Clip to the boundary
    buffer_clipped = arcpy.analysis.Clip(
        in_features=buffer_zone,
        clip_features=boundary,
        out_feature_class=os.path.join(workspace, "buffer_clipped")
    )

    # Determine candidate constraining geometry
    clip_count = int(arcpy.management.GetCount(buffer_clipped)[0])
    if clip_count > 0:
        constraint_fc = buffer_clipped
    else:
        # Fallback: if the annular ring fell outside the boundary (e.g., border vertex),
        # constrain candidates directly inside the administrative boundary
        arcpy.AddWarning("Buffer annulus fell completely outside administrative boundary. Falling back to boundary constraint.")
        constraint_fc = boundary

    # 4. Generate candidate points
    candidate_points = arcpy.management.CreateRandomPoints(
        out_path=workspace,
        out_name="point_candidates",
        constraining_feature_class=constraint_fc,
        number_of_points_or_field=50,
        create_multipoint_output="POINT"
    )

    # 5. Pick one random candidate
    oid_field = arcpy.Describe(candidate_points).OIDFieldName
    oids = [row[0] for row in arcpy.da.SearchCursor(candidate_points, [oid_field])]
    
    if not oids:
        raise ValueError("Failed to create random candidate points in the restricted zone.")

    random_oid = random.choice(oids)
    query = f"{arcpy.AddFieldDelimiters(candidate_points, oid_field)} = {random_oid}"
    
    selected_point = arcpy.management.SelectLayerByAttribute(
        in_layer_or_view=candidate_points,
        selection_type="NEW_SELECTION",
        where_clause=query
    )

    # 6. Extract WGS84 coordinates and the native geometry object
    sr_wgs84 = arcpy.SpatialReference(4326)
    target_sr = arcpy.Describe(point).spatialReference

    lat, lon, target_geom = None, None, None
    with arcpy.da.SearchCursor(selected_point, ["SHAPE@Y", "SHAPE@X"], spatial_reference=sr_wgs84) as cursor:
        for row in cursor:
            lat, lon = row[0], row[1]
            break

    with arcpy.da.SearchCursor(selected_point, ["SHAPE@"], spatial_reference=target_sr) as cursor:
        for row in cursor:
            target_geom = row[0]
            break

    # 7. Update target point geometry
    with arcpy.da.UpdateCursor(point, ["SHAPE@"]) as cursor:
        for row in cursor:
            row[0] = target_geom
            cursor.updateRow(row)
            break

    # 8. Clean up intermediate per-point features
    for temp_fc in ["outer_buffer", "inner_buffer", "buffer_zone", "buffer_clipped", "point_candidates"]:
        full_temp = os.path.join(workspace, temp_fc)
        if arcpy.Exists(full_temp):
            try:
                arcpy.management.Delete(full_temp)
            except Exception:
                pass

    return lat, lon


def displace_points(village_table, boundaries, max_distance, min_distance, workspace, boundary_admin_field="ADM1ADM2"):
    """
    Main displacement controller.
    """
    # Clear any inherited project-level constraints
    arcpy.env.workspace = workspace
    arcpy.env.overwriteOutput = True
    arcpy.env.extent = None
    arcpy.env.geographicTransformations = None

    # Load and prep base layers
    villages_feature = ingest_villages(village_table, "villages", workspace)
    villages_table = pd.read_csv(village_table)
    villages_table["old_Latitude"] = villages_table["Latitude"]
    villages_table["old_Longitude"] = villages_table["Longitude"]
    villages_table["ADM1ADM2"] = villages_table["ADM1ADM2"].astype(str).str.strip()
    villages_table["FNID"] = villages_table["FNID"].astype(str).str.strip()

    admins = ingest_admins(boundaries, workspace)

    # Create working feature layers to hold independent selections
    village_fl = "villages_layer"
    admins_fl = "admins_layer"

    if arcpy.Exists(village_fl):
        arcpy.management.Delete(village_fl)
    if arcpy.Exists(admins_fl):
        arcpy.management.Delete(admins_fl)

    arcpy.management.MakeFeatureLayer(villages_feature, village_fl)
    arcpy.management.MakeFeatureLayer(admins, admins_fl)

    # Process displacement per village
    for index, row in villages_table.iterrows():
        adm1adm2 = row[boundary_admin_field]
        fnid = row["FNID"]

        point_query = f"{arcpy.AddFieldDelimiters(village_fl, 'FNID')} = '{fnid}'"
        boundary_query = f"{arcpy.AddFieldDelimiters(admins_fl, boundary_admin_field)} = '{adm1adm2}'"

        arcpy.management.SelectLayerByAttribute(
            in_layer_or_view=village_fl,
            selection_type="NEW_SELECTION",
            where_clause=point_query
        )
        arcpy.management.SelectLayerByAttribute(
            in_layer_or_view=admins_fl,
            selection_type="NEW_SELECTION",
            where_clause=boundary_query
        )

        pt_count = int(arcpy.management.GetCount(village_fl)[0])
        bnd_count = int(arcpy.management.GetCount(admins_fl)[0])

        if pt_count == 0:
            arcpy.AddWarning(f"Village FNID '{fnid}' could not be selected. Skipping.")
            continue

        if bnd_count == 0:
            arcpy.AddWarning(f"No boundary found for code '{adm1adm2}' on FNID '{fnid}'. Skipping.")
            continue

        # Calculate new displaced point coordinates
        lat, lon = get_new_coordinates(village_fl, admins_fl, max_distance, min_distance, workspace)

        # Update pandas dataframe
        villages_table.at[index, "Latitude"] = lat
        villages_table.at[index, "Longitude"] = lon

        # Update layer attribute fields
        with arcpy.da.UpdateCursor(village_fl, ["Latitude", "Longitude"]) as cursor:
            for u_row in cursor:
                u_row[0] = lat
                u_row[1] = lon
                cursor.updateRow(u_row)

    # Clear selections on layers before returning
    arcpy.management.SelectLayerByAttribute(village_fl, "CLEAR_SELECTION")
    arcpy.management.SelectLayerByAttribute(admins_fl, "CLEAR_SELECTION")

    return villages_table, villages_feature