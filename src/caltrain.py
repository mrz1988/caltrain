from __future__ import print_function
import requests
import time
import json
import os
from datetime import datetime, timedelta, tzinfo
try:
    from datetime import timezone
    utc = timezone.utc
except ImportError:
    # Python2 compat
    class UTC(tzinfo):
        def utcoffset(self, dt):
            return timedelta(0)
        def tzname(self, dt):
            return "UTC"
        def dst(self, dt):
            return timedelta(0)
    utc = UTC()

def file(fp):
    return os.path.join(os.getcwd(), 'src', fp)

# Step 1: Make call to get all station names, including NB and SB keys
# Step 2: Make call to get all station expected train times and IDs for trains
# Step 3: Make call to get all train updates
# Step 4: Populate dict of stations by station name
# Step 5: Populate dict of trains in each station by train ID.
#     Part 1: For each train entry, pull the caltrain stop
#     Part 2: Create a train with the expected train time under the train's ID
# Step 6: Update train times with latest info
#     Part 1: Similar to above

debug = False

get_stations_url = "http://api.511.org/transit/stops?api_key=af0ee2b3-6832-4876-bb47-a4b8ac8eeaff&operator_id=CT"
get_stops_url = "http://api.511.org/transit/StopMonitoring?api_key=af0ee2b3-6832-4876-bb47-a4b8ac8eeaff&agency=CT"
get_trains_url = "http://api.511.org/transit/VehicleMonitoring?api_key=af0ee2b3-6832-4876-bb47-a4b8ac8eeaff&agency=CT"

def main():
    if debug:
        with open(file('stations.json'), 'r') as f:
            stations_json = json.load(f)
        with open(file('expected_stops.json'), 'r') as f:
            expected_stops_json = json.load(f)
        with open(file('train_timings.json'), 'r') as f:
            train_timings_json = json.load(f)
    else:
        stations_json = requests.get(get_stations_url).json()
        train_timings_json = requests.get(get_trains_url).json()
        with open('stations.json', 'w') as f:
            json.dump(stations_json, f)
        with open('train_timings.json', 'w') as f:
            json.dump(train_timings_json, f)
    timings = CaltrainTimings(stations_json)
    timings.update_trains(train_timings_json)
    timings.print_output()


def convert_time(time_string):
    frmt = "%Y-%m-%dT%H:%M"
    dt = datetime.strptime(time_string[:-4], frmt)
    dt.replace(tzinfo=utc)
    return dt


def to_localtime(dt):
    now_time = time.time()
    offset = datetime.fromtimestamp(now_time) - datetime.utcfromtimestamp(now_time)
    return dt + offset


class CaltrainTimings(object):
    def __init__(self, stations_json):
        self.stations = self.parse_stations(stations_json)

    def parse_stations(self, stations_json):
        stations = stations_json["Contents"]["dataObjects"]["ScheduledStopPoint"]
        stations_dict = {}
        for station_json in stations:
            name = station_json["Name"]
            # There's a weird Tamien station that I'm skipping here
            if "Station" in name:
                continue
            name = "{origname} Station".format(origname=name)
            id = station_json["id"][:-1]
            if stations_dict.get(id) is None:
                stations_dict[id] = CaltrainStation(name)
        return stations_dict


    def update_trains(self, expected_stops_json, train_timings_json):
        self.clear_trains()
        self.parse_stops(expected_stops_json)
        self.parse_trains(train_timings_json)

    def clear_trains(self):
        for station_id in self.stations:
            station = self.stations[station_id]
            station.northbound_trains = {}
            station.southbound_trains = {}

    def parse_stops(self, stops_json):
        stops = stops_json["ServiceDelivery"]["StopMonitoringDelivery"]["MonitoredStopVisit"]
        for stop in stops:
            stop_info = stop["MonitoredVehicleJourney"]
            train_id = stop_info["FramedVehicleJourneyRef"]["DatedVehicleJourneyRef"]
            train_type = stop_info["LineRef"]
            is_nb = stop_info["DirectionRef"] == "NB"

            call_info = stop_info["MonitoredCall"]
            station_id = call_info["StopPointRef"][:-1]
            departure_time_str = call_info["AimedDepartureTime"]
            aimed_departure = convert_time(departure_time_str)
            station = self.stations[station_id]
            train = Caltrain(train_id, train_type, aimed_departure)
            if is_nb:
                station.northbound_trains[train_id] = train
            else:
                station.southbound_trains[train_id] = train

    def parse_trains(self, train_timings_json):
        trains = train_timings_json["Siri"]["ServiceDelivery"]["VehicleMonitoringDelivery"]["VehicleActivity"]
        for train in trains:
            train_info = train["MonitoredVehicleJourney"]
            train_id = train_info["VehicleRef"]
            is_nb = "NB" in train_info["DirectionRef"]
            try:
                stops = train_info["OnwardCall"]["OnwardCall"]
            except KeyError:
                # Apparently, there are some edge cases where this happens
                # and the JSON structures are different. I have no clue why.
                # It seems to happen for newer trains?
                stops = train_info["OnwardCalls"]["OnwardCall"]
            for stop in stops:
                station_id = stop["StopPointRef"][:-1]
                departure_time_str = stop["ExpectedDepartureTime"]
                expected_departure = convert_time(departure_time_str)
                station = self.stations[station_id]
                try:
                    if is_nb:
                        train = station.northbound_trains[train_id]
                    else:
                        train = station.southbound_trains[train_id]
                    train.expected_departure = expected_departure
                except:
                    pass

    def print_output(self):
        for station_id in self.stations:
            print(str(self.stations[station_id]))
            print("*" * 50)


class CaltrainStation(object):
    def __init__(self, name):
        self.name = name
        self.nb_id = None
        self.sb_id = None
        self.northbound_trains = {}
        self.southbound_trains = {}

    def __str__(self):
        builder = [self.name + ":", "Northbound Trains:"]

        by_departure = lambda t: t.aimed_departure
        for train in sorted(self.northbound_trains.values(), key=by_departure):
            builder.append("    {train}".format(train=train))
        builder.append("Southbound Trains:")
        for train in sorted(self.southbound_trains.values(), key=by_departure):
            builder.append("    {train}".format(train=train))
        return "\n".join(builder)


class Caltrain(object):
    def __init__(self, id, train_type, aimed_departure):
        self.id = id
        self.train_type = train_type
        self.aimed_departure = aimed_departure
        self.expected_departure = None

    def __str__(self):
        if self.expected_departure is None:
            return "?"
        minutes_late = (self.expected_departure - self.aimed_departure).seconds // 60
        if minutes_late > 0:
            print(self.expected_departure)
            print(self.aimed_departure)
            late_msg = " ({late} minutes late)".format(late=minutes_late)
        else:
            late_msg = " (On time)"
        date_local = to_localtime(self.expected_departure)
        frmt = "%I:%M%p"
        formatted = datetime.strftime(date_local, frmt)
        return "{id:5}{time:10}{late}".format(id=self.id, time=formatted, late=late_msg)


if __name__ == '__main__':
    main()