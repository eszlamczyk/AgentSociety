import os
os.environ["OVERPASS_URL"] = "https://overpass.kumi.systems/api/interpreter"

from mosstool.map.osm import RoadNet, Building, PointOfInterest
from mosstool.map.builder import Builder
from mosstool.util.format_converter import dict2pb
from mosstool.type import Map

if __name__ == "__main__":
    # Beijing center projection
    projstr = "+proj=tmerc +lat_0=39.9 +lon_0=116.4"

    # Bounding box: smaller central Beijing area
    min_lat = 39.85
    max_lat = 39.95
    min_lon = 116.35
    max_lon = 116.45

    print("Fetching road network from OSM...")
    rn = RoadNet(
        proj_str=projstr,
        max_latitude=max_lat,
        min_latitude=min_lat,
        max_longitude=max_lon,
        min_longitude=min_lon,
    )
    roadnet = rn.create_road_net("cache/topo.geojson")

    print("Fetching buildings/AOIs from OSM...")
    building = Building(
        proj_str=projstr,
        max_latitude=max_lat,
        min_latitude=min_lat,
        max_longitude=max_lon,
        min_longitude=min_lon,
    )
    aois = building.create_building("cache/aois.geojson")

    print("Fetching POIs from OSM...")
    poi = PointOfInterest(
        max_latitude=max_lat,
        min_latitude=min_lat,
        max_longitude=max_lon,
        min_longitude=min_lon,
    )
    pois = poi.create_pois("cache/pois.geojson")

    print("Building map...")
    builder = Builder(
        net=roadnet,
        aois=aois,
        pois=pois,
        proj_str=projstr,
    )
    m = builder.build("beijing")

    print("Saving to agentsociety_data/beijing.pb...")
    pb = dict2pb(m, Map())
    with open("agentsociety_data/beijing.pb", "wb") as f:
        f.write(pb.SerializeToString())

    print("Done!")
