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


# Preload JSON for configurations
STOPS_FP = 'stops.json'
CONFIG_FP = 'config.json'

# Debug json dump file paths
STATIONS_DEBUG_FP = 'stations.json'
TRAIN_TIMINGS_DEBUG_FP = 'train_timings.json'


debug = False


get_stations_url = "http://api.511.org/transit/stops?api_key=af0ee2b3-6832-4876-bb47-a4b8ac8eeaff&operator_id=CT"
get_stops_url = "http://api.511.org/transit/StopMonitoring?api_key=af0ee2b3-6832-4876-bb47-a4b8ac8eeaff&agency=CT"
get_trains_url = "http://api.511.org/transit/VehicleMonitoring?api_key=af0ee2b3-6832-4876-bb47-a4b8ac8eeaff&agency=CT"

def main():
    if debug:
        with open(STATIONS_DEBUG_FP, 'r') as f:
            stations_json = json.load(f)
        with open(TRAIN_TIMINGS_DEBUG_FP, 'r') as f:
            train_timings_json = json.load(f)
    else:
        stations_json = requests.get(get_stations_url).json()
        train_timings_json = requests.get(get_trains_url).json()
        with open(STATIONS_DEBUG_FP, 'w') as f:
            json.dump(stations_json, f)
        with open(TRAIN_TIMINGS_DEBUG_FP, 'w') as f:
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


    def update_trains(self, train_timings_json):
        self.clear_trains()
        self.parse_trains(train_timings_json)

    def clear_trains(self):
        for station_id in self.stations:
            station = self.stations[station_id]
            station.northbound_trains = {}
            station.southbound_trains = {}

    def parse_trains(self, train_timings_json):
        trains = train_timings_json["Siri"]["ServiceDelivery"]["VehicleMonitoringDelivery"]["VehicleActivity"]
        for train in trains:
            train_info = train["MonitoredVehicleJourney"]
            train_id = train_info["VehicleRef"]
            train_type = train_info["LineRef"]
            is_nb = "North" == train_info["DirectionRef"]
            stops = train_info["OnwardCalls"]["OnwardCall"]
            for stop in stops:
                station_id = stop["StopPointRef"][:-1]
                aim_departure_str = stop["AimedDepartureTime"]
                exp_departure_str = stop["ExpectedDepartureTime"]
                aimed_departure = convert_time(aim_departure_str)
                expected_departure = convert_time(exp_departure_str)
                station = self.stations[station_id]
                train = Caltrain(
                    id=train_id,
                    train_type=train_type,
                    aimed_departure=aimed_departure,
                    expected_departure=expected_departure
                )
                if is_nb:
                    station.northbound_trains[train_id] = train
                else:
                    station.southbound_trains[train_id] = train

    def print_output(self):
        for station_id in self.stations:
            if "Mountain" not in self.stations[station_id].name:
                continue
            print(self.stations[station_id].format_output())


class CaltrainStation(object):
    def __init__(self, name):
        self.name = name
        self.nb_id = None
        self.sb_id = None
        self.northbound_trains = {}
        self.southbound_trains = {}

    def format_output(self):
        builder = [self.name + ":", "Northbound Trains:"]

        by_departure = lambda t: t.aimed_departure
        if len(self.northbound_trains) == 0:
            builder.append("    No upcoming trains.")
        for train in sorted(self.northbound_trains.values(), key=by_departure):
            builder.append("    {train}".format(train=train.format_output()))
        builder.append("Southbound Trains:")
        if len(self.southbound_trains) == 0:
            builder.append("    No upcoming trains.")
        for train in sorted(self.southbound_trains.values(), key=by_departure):
            builder.append("    {train}".format(train=train.format_output()))
        return "\n".join(builder)


class Caltrain(object):
    def __init__(self, id, train_type, aimed_departure, expected_departure):
        self.id = id
        self.train_type = train_type
        self.aimed_departure = aimed_departure
        self.expected_departure = expected_departure

    def format_output(self):
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


def load_stops():
    with open(STOPS_FP, 'r') as f:
        try:
            stops = json.load(f)['stops']
        except Exception as ex:
            print(ex)
            return None
    return stops


if __name__ == '__main__':
    main()