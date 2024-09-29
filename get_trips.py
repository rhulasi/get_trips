#!/usr/bin/env python
# coding: utf-8
from datetime import timedelta
from tqdm import tqdm
import config
import country_converter as coco
import json
import pandas as pd
import requests

USERNAME=config.USERNAME
PASSWORD=config.PASSWORD

def getFlights(air):
    flights=[]
    if isinstance(air,dict):
        air = [air]
    for a in air:
        s=a['Segment']
        if isinstance(s, dict):
            # Single flight segment present so wrap in a list
            s = [s]
        for f in s:
            flight={}
            # Try the operating airline first, then codeshare
            try:
                airline=(f['operating_airline_code'])
                flight_no=airline+f['operating_flight_number']
            except KeyError:
                try:
                    airline=(f['marketing_airline_code'])
                    flight_no=airline+f['marketing_flight_number']
                except KeyError:
                    # No airline code
                    flight_no='Unspecified'
            
            # Get seat information at time of booking
            try:
                seats=(f['seats'])
            except KeyError:
                # No seat
                seats='Unspecified'
            try:
                flight['aircraft']=f['aircraft']
            except KeyError:
                flight['aircraft']='Unspecified'
            
            flight['trip_id']=a['trip_id']
            flight['flight_id']=f['id']
            flight['flight_no']=flight_no
            
            flight['date']=f['StartDateTime']['date']
            flight['route']=f['start_airport_code']+'-'+f['end_airport_code']
            flight['seats']=seats
            flights.append(flight)
    return(flights)

def getLodgingCountries(l):
    if isinstance(l, dict):
        # Single lodging present so wrap in a list
        l = [l]
    countries = []
    for m in l:
        try:
            country = m['Address']['country']
        except KeyError:
            country = 'Unknown'
        countries.append(country)
    # Dedupe and flatten
    countriesList = list(dict.fromkeys(countries))
    return(countriesList)

response = requests.get('https://api.tripit.com/v1/list/trip/past/true/format/json', auth=(USERNAME,PASSWORD))
pastTrips = response.json()
pages = int(pastTrips['max_page'])
print('{0} pages of trips to retrieve'.format(pages))

# Paginate through all pages and collect trip information
allPastTrips = []
for i in tqdm(range(1,pages+1)):
    response = requests.get('https://api.tripit.com/v1/list/trip/past/true/format/json/page_num/{0}'.format(i), auth=(USERNAME,PASSWORD))
    output = response.json()
    if isinstance(output['Trip'], dict):
        # Single trip returned so we need to wrap it in a list to enable dataframe conversion
        singleTrip = []
        singleTrip.append(response.json()['Trip'])
        output['Trip'] = singleTrip
    df = pd.json_normalize(output,record_path=['Trip'])
    allPastTrips.append(df)
allPastTrips = pd.concat(allPastTrips,ignore_index=True)

# Sort descending by end date because API returns in order of TripID
allPastTrips.sort_values(by=['end_date'],ascending=False,inplace=True)

# Convert dates
allPastTrips[['start_date','end_date']] = allPastTrips[['start_date','end_date']].apply(pd.to_datetime)

# Add URL to the trip
allPastTrips['trip_url']='https://www.tripit.com/app/trips/' + allPastTrips['id']

# Add lodging countries for trips and get flight information
tripLodgingLocations = {}
tripsWithUnknownLocations = []
allFlights = []
print('Extracting country information from lodging details and flight info')
for i in tqdm(allPastTrips['id'].to_list()):
    response = requests.get('https://api.tripit.com/v1/get/trip/id/{0}/include_objects/true/format/json'.format(i), auth=(USERNAME,PASSWORD))
    try:
        lodging = response.json()['LodgingObject']
        lodgingLocation = getLodgingCountries(lodging)
        if 'Unknown' in lodgingLocation:
            # Capture details of unknown lodging locations for remediation
            df = pd.json_normalize(lodging)
            tripsWithUnknownLocations.append(df)
        tripLodgingLocations[str(i)] = lodgingLocation
    except KeyError:
        # No lodging
        None
    try:
        air = response.json()['AirObject']
        flights = getFlights(air)
        df = pd.json_normalize(flights)
        allFlights.append(df)
    except KeyError:
        # No flights
        None

allPastTrips['lodgingCountries']=allPastTrips['id'].map(tripLodgingLocations)

# Create a column containing all countries on the trip, both flight and lodging
allPastTrips['allCountries'] = [v[pd.notna(v)] for v in allPastTrips[['PrimaryLocationAddress.country','lodgingCountries']].values]
allPastTrips['allCountries'] = allPastTrips['allCountries'].apply(lambda x: list(pd.core.common.flatten(x))).apply(set).apply(list)

# Replace country codes with names and flatten
print('Looking up country codes')
allPastTrips['allCountries'] = allPastTrips['allCountries'].apply(lambda x: coco.convert(names=x, to='name_short'))
allPastTrips['allCountries'] = allPastTrips['allCountries'].apply(lambda x: x if isinstance(x, str) else ', '.join([str(y) for y in x]))

# Filter to international trips
allPastInternationalTrips=allPastTrips.loc[allPastTrips['PrimaryLocationAddress.country'] !='US',['id','trip_url','display_name','primary_location',
                                                                                                  'PrimaryLocationAddress.country','lodgingCountries',
                                                                                                  'allCountries','start_date','end_date']]

# Calculate days not present in USA (departure and return days not included as per:)
# https://www.uscis.gov/policy-manual/volume-12-part-d-chapter-4#
allPastInternationalTrips['non_present_days'] = (allPastInternationalTrips['end_date'] - allPastInternationalTrips['start_date'] - timedelta(days=1)).dt.days

# Account for same day trips
allPastInternationalTrips['non_present_days'].clip(lower=0,inplace=True)

print('Writing output')
# Write outputs to an Excel document
with pd.ExcelWriter('PastTrips.xlsx',engine='xlsxwriter') as writer:  
    allPastInternationalTrips.to_excel(writer,sheet_name='All Past International Trips',freeze_panes=(1,0),\
                                       columns=['id','trip_url','display_name','primary_location',\
                                                'PrimaryLocationAddress.country','lodgingCountries',\
                                                'start_date','end_date','allCountries','non_present_days'])
    allPastTrips.to_excel(writer, sheet_name='All Past Trips',freeze_panes=(1,0))
    if len(tripsWithUnknownLocations)>0:
        tripsWithUnknownLocations = pd.concat(tripsWithUnknownLocations,ignore_index=True)
        tripsWithUnknownLocations = tripsWithUnknownLocations[tripsWithUnknownLocations['Address.country'].isnull()]
        tripsWithUnknownLocations['trip_url']='https://www.tripit.com/app/trips/' + tripsWithUnknownLocations['trip_id']
        tripsWithUnknownLocations.to_excel(writer,sheet_name='Trips with unknown locations',freeze_panes=(1,0),\
                                      columns=['id', 'trip_id','display_name','Address.address','Address.country','trip_url'])
    allFlights = pd.concat(allFlights,ignore_index=True)
    allFlights.to_excel(writer,sheet_name='All Flights',freeze_panes=(1,0),columns=['trip_id','flight_id','date','flight_no','route','aircraft','seats'])

print('Done!')