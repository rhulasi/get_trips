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
        output['Trip']=singleTrip
    df = pd.json_normalize(output,record_path=['Trip'])
    allPastTrips.append(df)
allPastTrips = pd.concat(allPastTrips,ignore_index=True)

# Convert dates
allPastTrips[['start_date','end_date']] = allPastTrips[['start_date','end_date']].apply(pd.to_datetime)

# Calculate days not present in USA (departure and return days not included as per:)
# https://www.uscis.gov/policy-manual/volume-12-part-d-chapter-4#
allPastTrips['non_present_days'] = (allPastTrips['end_date'] - allPastTrips['start_date'] - timedelta(days=1)).dt.days

# Account for same day trips
allPastTrips['non_present_days'].clip(lower=0,inplace=True)

# Add URL to the trip
allPastTrips['trip_url']='https://www.tripit.com/app/trips/' + allPastTrips['id']

# Filter to international trips
allPastInternationalTrips=allPastTrips.loc[allPastTrips['PrimaryLocationAddress.country'] !='US',['id','trip_url','display_name','primary_location','PrimaryLocationAddress.country','start_date','end_date','non_present_days']]

# Add lodging countries for international trips
tripLodgingLocations = {}
tripsWithUnknownLocations = []
print('Extracting country information from lodging details')
for i in tqdm(allPastInternationalTrips['id'].to_list()):
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

allPastInternationalTrips['lodgingCountries']=allPastInternationalTrips['id'].map(tripLodgingLocations)

# Create a column containing all countries on the trip, both flight and lodging
allPastInternationalTrips['allCountries'] = [v[pd.notna(v)] for v in allPastInternationalTrips[['PrimaryLocationAddress.country','lodgingCountries']].values]
allPastInternationalTrips['allCountries'] = allPastInternationalTrips['allCountries'].apply(lambda x: list(pd.core.common.flatten(x))).apply(set).apply(list)

# Replace country codes with names and flatten
print('Looking up country codes')
allPastInternationalTrips['allCountries'] = allPastInternationalTrips['allCountries'].apply(lambda x: coco.convert(names=x, to='name_short'))
allPastInternationalTrips['allCountries'] = allPastInternationalTrips['allCountries'].apply(lambda x: x if isinstance(x, str) else ', '.join([str(y) for y in x]))

print('Writing output')
# Write outputs to an Excel document
with pd.ExcelWriter('PastTrips.xlsx',engine='xlsxwriter') as writer:  
    allPastInternationalTrips.to_excel(writer, sheet_name='All Past International Trips',freeze_panes=(1,0),\
                                       columns=['id','trip_url','display_name','primary_location',\
                                                'PrimaryLocationAddress.country','lodgingCountries',\
                                                'start_date','end_date','allCountries','non_present_days'])
    allPastTrips.to_excel(writer, sheet_name='All Past Trips',freeze_panes=(1,0))
    if len(tripsWithUnknownLocations)>0:
        tripsWithUnknownLocations = pd.concat(tripsWithUnknownLocations,ignore_index=True)
        tripsWithUnknownLocations = tripsWithUnknownLocations[tripsWithUnknownLocations['Address.country'].isnull()]
        tripsWithUnknownLocations['trip_url']='https://www.tripit.com/app/trips/' + tripsWithUnknownLocations['trip_id']
        tripsWithUnknownLocations.to_excel(writer, sheet_name='Trips with unknown locations',freeze_panes=(1,0),\
                                      columns=['id', 'trip_id','display_name','Address.address','Address.country','trip_url'])
print('Done!')