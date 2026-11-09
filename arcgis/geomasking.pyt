# -*- coding: utf-8 -*-
import os
import sys
import importlib
import pandas as pd
import arcpy

# Ensure script directory is on sys.path
tool_dir = os.path.dirname(os.path.abspath(__file__))
if tool_dir not in sys.path:
    sys.path.append(tool_dir)

# Import custom module
import geomasking_arcgis

arcpy.env.overwriteOutput = True


class Toolbox(object):
    def __init__(self):
        self.label = "Toolbox"
        self.alias = "toolbox"
        self.tools = [Geomasking]


class Geomasking(object):
    def __init__(self):
        self.label = "Geomasking"
        self.description = "Geomasking tool"
        self.canRunInBackground = False

    def getParameterInfo(self):
        workspace = arcpy.Parameter(
            displayName="Workspace GDB",
            name="workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input"            
        )        
        village_table = arcpy.Parameter(
            displayName="Village table (csv)",
            name="village_table",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        boundaries = arcpy.Parameter(
            displayName="Boundaries (Displacement restriction level)",
            name="boundaries",
            datatype=["GPLayer", "DEShapeFile", "DEFeatureClass"],
            parameterType="Required",
            direction="Input"
        )
        max_distance = arcpy.Parameter(
            displayName="Maximum displacement distance (meters)",
            name="max_distance",
            datatype="GPLong",
            parameterType="Required",
            direction="Input"
        )
        min_distance = arcpy.Parameter(
            displayName="Minimum displacement distance (meters)",
            name="min_distance",
            datatype="GPLong",
            parameterType="Required",
            direction="Input"
        )
        out_name = arcpy.Parameter(
            displayName="Output displaced coordinates",
            name="out_disp_name",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"
        )
        out_dir = arcpy.Parameter(
            displayName="Output directory",
            name="out_dir",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input"
        )
        return [workspace, village_table, boundaries, max_distance, min_distance, out_name, out_dir]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        params = {p.name: p for p in parameters}
        max_dist = params["max_distance"]
        min_dist = params["min_distance"]
        if min_dist.value is not None and max_dist.value is not None:
            if not (max_dist.value > min_dist.value):
                min_dist.setErrorMessage("The minimum distance cannot be larger than the maximum distance.")
        return

    def execute(self, parameters, messages):
        # Force fresh import of module logic on each run
        importlib.reload(geomasking_arcgis)

        arcpy.AddMessage("Displacing village locations...")
        params = {p.name: p for p in parameters}

        # Run displacement routine
        village_df, village_feature = geomasking_arcgis.displace_points(
            village_table=params["village_table"].valueAsText, 
            boundaries=params["boundaries"].valueAsText, 
            max_distance=params["max_distance"].value, 
            min_distance=params["min_distance"].value, 
            workspace=params["workspace"].valueAsText, 
            boundary_admin_field="ADM1ADM2"
        )

        # Write output to the user-specified feature class
        out_fc = params["out_disp_name"].valueAsText
        if out_fc:
            if arcpy.Exists(out_fc):
                arcpy.management.Delete(out_fc)
            arcpy.conversion.ExportFeatures(village_feature, out_fc)
            parameters[5].value = out_fc

        # Save displaced coordinate table to CSV
        out_dir_path = params["out_dir"].valueAsText
        out_csv_path = os.path.join(out_dir_path, "Displacement_output.csv")
        village_df.to_csv(out_csv_path, index=False)

        arcpy.AddMessage(f"Completed displacement. Total of {len(village_df)} points displaced.")
        arcpy.AddMessage(f"Output table saved in {out_dir_path}")

        return

    def postExecute(self, parameters):
        return