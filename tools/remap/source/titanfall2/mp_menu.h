/* Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later. */
#pragma once
#include <cmath>
#include <string>
#include <vector>

// Editor point prefab. Keep the paired engine anchors and their isolated
// lighting together when moving a menu scene to another map.
inline void ExpandMPMenuPrefabs() {
    std::vector<entity_t> generated;
    int count = 0;
    for (entity_t &source : entities) {
        if (!striEqual(source.valueForKey("classname"), "mrvn_mp_menu")) continue;
        if (++count > 1) Error("Only one mrvn_mp_menu may be placed per map");
        Vector3 origin(0), angles(0);
        source.read_keyvalue(origin, "origin"); source.read_keyvalue(angles, "angles");
        const float yaw = angles.y();
        const double radians = yaw * 3.141592653589793 / 180.0;
        float distance = 256, height = 40;
        source.read_keyvalue(distance, "camera_distance"); source.read_keyvalue(height, "camera_height");
        int environment = 1;
        source.read_keyvalue(environment, "lightEnvironmentIndex");
        if (environment < 1 || environment > 3 || !std::isfinite(distance) || distance < 64 ||
            !std::isfinite(height)) Error("Invalid mrvn_mp_menu lighting/camera settings");
        auto at = [&](float x, float y, float z) {
            // Local front is -Y, as the retail menu anchor at yaw -90.
            const double rotation = (yaw + 90) * 3.141592653589793 / 180.0;
            return std::to_string(origin.x() + x * cos(rotation) - y * sin(rotation)) + " " +
                   std::to_string(origin.y() + x * sin(rotation) + y * cos(rotation)) + " " +
                   std::to_string(origin.z() + z);
        };
        auto make = [&](const char *classname, float x, float y, float z) -> entity_t& {
            entity_t &e = generated.emplace_back();
            e.setKeyValue("classname", classname); e.setKeyValue("origin", at(x,y,z).c_str());
            return e;
        };
        source.setKeyValue("classname", "info_target_clientside");
        source.setKeyValue("script_name", "menu_scene_ref");
        source.setKeyValue("scale", "1");
        entity_t &camera = make("info_target_clientside",0,-distance,height);
        camera.setKeyValue("script_name", "menu_camera_target");
        camera.setKeyValue("angles", ("0 " + std::to_string(yaw+180) + " 0").c_str());
        camera.setKeyValue("scale", "1");
        const std::string index = "*" + std::to_string(environment);
        entity_t &sun = make("light_environment",0,0,256);
        sun.setKeyValue("lightEnvironmentIndex",index.c_str());
        sun.setKeyValue("angles",("51 " + std::to_string(yaw+212) + " 0").c_str());
        sun.setKeyValue("pitch","-51"); sun.setKeyValue("_light","255 245 225 510");
        sun.setKeyValue("_ambient","210 235 255 90");
        entity_t &volume = make("light_environment_volume",0,0,0);
        volume.setKeyValue("lightEnvironmentIndex",index.c_str());
        volume.setKeyValue("*trigger_bounds_mins","-2048 -2048 -512");
        volume.setKeyValue("*trigger_bounds_maxs","2048 2048 2048");
        const char *normals[] = {"-1 0 0 2048","1 0 0 2048","0 -1 0 2048","0 1 0 2048","0 0 -1 512","0 0 1 2048"};
        for (int i=0; i<6; ++i)
            volume.setKeyValue(("*trigger_brush_0_plane_"+std::to_string(i)).c_str(),normals[i]);
        entity_t &key = make("light_spot",-140,-220,200);
        key.setKeyValue("angles",("35 "+std::to_string(yaw+148)+" 0").c_str());
        key.setKeyValue("pitch","-35"); key.setKeyValue("_light","255 236 214 600");
        key.setKeyValue("_zero_percent_distance","700"); key.setKeyValue("_fifty_percent_distance","350");
        key.setKeyValue("_cone","55");key.setKeyValue("_inner_cone","35");key.setKeyValue("realtime","1");
    }
    entities.insert(entities.end(),std::make_move_iterator(generated.begin()),std::make_move_iterator(generated.end()));
}
