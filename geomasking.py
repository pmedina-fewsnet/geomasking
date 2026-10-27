# ===============
# Author: Paulo Medina
# Chemonics
# FEWS NET
# Date: 2026-10-23
# ==============

# Import modules
from matplotlib import pyplot as plt
import geopandas as gpd
import pandas as pd
import random
import os

# ================
# Script
# ================

# -------------------------
# Ingest village data
# -------------------------
def ingest_villages(table):
    """
    Load village points in csv or excel format
    
    Parameters
    ----------
    table : String path
    Table containing village id, latitude, longitude, Admin1, Admin2, Admin3.
    
    Returns
    -------
    A GeoDataFrame.
    """
    # Read into regular dataframe
    if table.endswith(".csv"):
        df = pd.read_csv(table)
    elif table.endswith(".xlsx"):
        df = pd.read_excel(table)
    else:
        print(f"File {table} is not valid.")
        raise(TypeError)
    # Load geodataframe
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["Longitude"], df["Latitude"]),
        crs="EPSG:4326"
    )
    # Convert to UTM for distance operations
    gdf_meters = gdf.to_crs(gdf.estimate_utm_crs())
    # Return gdf in UTM
    return gdf_meters

# -----------------------
# Ingest admin boundaries
# -----------------------
def ingest_admins(admin_path, admin1="ADMIN1", admin2="ADMIN2"):
    gdf = gpd.read_file(admin_path)
    gdf["ADM1ADM2"] = gdf[admin1] + gdf[admin2]
    gdf_meters = gdf.to_crs(gdf.estimate_utm_crs())
    return gdf_meters

# ------------------------
# Calculate new coodinates
# ------------------------
def get_new_coordinates(point, max_dist, min_dist, boundary):
    """
    Create new coordinates for each ingested point.

    Parameters
    ----------
    point : GeoDataFrame
        Village point location data.
    min_dist : Integer
        Minimun displacement distance.
    max_dist : Integer
        Maximum displacement distance.

    Returns
    -------
    new_points : Geometries
        Geodataframe with sampled points.
    """
    # Create a buffer zone around the point to the max distance
    buffer_zone = point.buffer(max_dist)
    ring_zone = point.buffer(min_dist)
    buffer = buffer_zone.difference(ring_zone)
    # Create a set of random points within the buffer zone
    points = gpd.GeoSeries([buffer]).sample_points(100).set_crs(boundary.crs)
    exploded = points.explode(index_parts=True)
    # Check against boundary
    valid_candidates = []
    for new_point in exploded:
        # Check if the point is within the correct boundary
        if boundary.geometry.iloc[0].contains(new_point):
            valid_candidates.append(new_point)
    # Select a random point from the valid candidates
    new_geometry = valid_candidates[random.randrange(0, len(valid_candidates))]
    point_wgs84 = gpd.GeoSeries([new_geometry], crs=boundary.crs).to_crs("EPSG:4326")
    # Return new sampled points
    return point_wgs84

# -----------------
# Get admin feature
# -----------------
def get_admin_feature(point_admin, boundary, boundary_admin_field):
    """
    Parameters
    ----------
    point_admin : String
        Admin/Concatenated names to mask the file.
    boundary : GeoPandas Geometry
        Admin boundaries.
    boundary_admin_field : String
        Name field.

    Returns
    -------
    feature : Geopandas Geoseries
        Geopandas geometry.
    """
    mask = boundary[boundary_admin_field] == point_admin
    feature = boundary[mask]
    return feature

# -------------------------
# Get displacement distance
# -------------------------
def get_displacement_distance(displaced_df):
    undisplaced = gpd.GeoDataFrame(displaced_df,geometry=gpd.points_from_xy(displaced_df.old_Longitude, displaced_df.old_Latitude, crs="EPSG:4326"))
    displaced = gpd.GeoDataFrame(displaced_df, geometry=gpd.points_from_xy(displaced_df.Longitude, displaced_df.Latitude, crs="EPSG:4326"))
    # Set target UTM CRS
    target_crs = undisplaced.estimate_utm_crs()
    # Set common index for distance check
    undisplaced.to_crs(target_crs, inplace=True)
    displaced.to_crs(target_crs, inplace=True)
    # Compute distance check
    displaced["Displacement distance"] = undisplaced.distance(displaced)
    return displaced

# ---------------
# Displace points
# ---------------
def displace_points(villages_table, max_distance, min_distance, boundary, boundary_admin_field="ADM1ADM2"):
    """
    Parameters
    ----------
    villages_table : TYPE
        DESCRIPTION.
    max_distance : TYPE
        DESCRIPTION.
    min_distance : TYPE
        DESCRIPTION.
    boundary : TYPE
        DESCRIPTION.
    boundary_admin_field : TYPE, optional
        DESCRIPTION. The default is "ADM1ADM2".

    Returns
    -------
    villages : TYPE
        DESCRIPTION.
    """
    # Ingest villages
    villages = ingest_villages(villages_table)
    admin = ingest_admins(boundary)
    villages["old_Latitude"] = villages["Latitude"]
    villages["old_Longitude"] = villages["Longitude"]
    # Create point displacements
    for index, row in villages.iterrows():
        geometry = row.geometry
        admin_name = row["ADM1ADM2"]
        boundary_feature = get_admin_feature(admin_name, admin, boundary_admin_field)
        new_geometry = get_new_coordinates(geometry, max_distance, min_distance, boundary_feature)
        villages.at[index, 'Latitude'] = float(new_geometry.y.iloc[0])
        villages.at[index, 'Longitude'] = float(new_geometry.x.iloc[0])
    villages = get_displacement_distance(villages)
    villages = villages.drop(["geometry"], axis=1)
    return villages
    
# -------------------
# Report displacement
# -------------------
def get_report(df, boundary):
    # Load two datasets
    undisplaced = gpd.GeoDataFrame(df,geometry=gpd.points_from_xy(df.old_Longitude, df.old_Latitude, crs="EPSG:4326"))
    displaced = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.Longitude, df.Latitude, crs="EPSG:4326"))
    # Distance metrics
    max_displacement = df["Displacement distance"].max()
    min_displacement = df["Displacement distance"].min()
    avg_displacement = df["Displacement distance"].mean()
    # Print report
    print("="*50)
    print("DISPLACEMENT REPORT")
    print("="*50)
    print()
    print(f"\t- Maximum displacement distance: {max_displacement}")
    print(f"\t- Minimum displacement distance: {min_displacement}")
    print(f"\t- Mean displacement distance: {avg_displacement}")
    print()
    base = boundary.plot(figsize=(10,5), color="white", edgecolor="black")
    undisplaced.plot(ax=base, marker='o', color="blue",markersize=5, label="Undisplaced")
    displaced.plot(ax=base, marker='x', color="red",markersize=5, label="Displaced")
    plt.legend()
    plt.show()
    
# ----
# Main
# ----
def main():
    village_path = input("Provide the prepared village data (csv or xlsx): ")
    boundary_path = input("Provide the boundary path data: ")
    max_distance = int(input("Provide the maximum displacement distance (meters): "))
    min_distance = int(input("Provide the minimum displacement distance: "))
    output_path = input("Provide an output path: ")
    output_name = input("Provide an output file name: ")
    displaced_df = displace_points(village_path, max_distance, min_distance, boundary_path, boundary_admin_field="ADM1ADM2")
    get_report(displaced_df, gpd.read_file(boundary_path))
    displaced_df.to_csv(os.path.join(output_path,output_name), index=False)