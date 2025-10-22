from bluepy.btle import Scanner, DefaultDelegate, BTLEDisconnectError


class ScanDelegate(DefaultDelegate):
    def __init__(self):
        DefaultDelegate.__init__(self)

    def handleDiscovery(self, dev, isNewDev, isNewData):
        if isNewDev:
            print("Discovered device", dev.addr)
        elif isNewData:
            print("Received new data from", dev.addr)


print("Creating scanner...")
scanner = Scanner().withDelegate(ScanDelegate())
print("Scanning...")

try:
    devices = scanner.scan(10.0)
except BTLEDisconnectError as e:
    print(f"Scan finished with BTLEDisconnectError: {e}")
    devices = []
except Exception as e:
    print(f"Scan finished with exception: {e}")
    devices = []

print("Finished.")

for dev in devices:
    print(f"Device {dev.addr} ({dev.addrType}), RSSI={dev.rssi} dB")
    for adtype, desc, value in dev.getScanData():
        print(f"{desc} = {value}")
