#!/usr/bin/env python
# coding: utf-8
from datetime import timedelta
from tqdm import tqdm
import config
import json
import pandas as pd
import requests

USERNAME=config.USERNAME
PASSWORD=config.PASSWORD

response = requests.get('https://api.tripit.com/v1/list/trip/past/true/format/json', auth=(USERNAME,PASSWORD))
pastTrips = response.json()
pages = int(pastTrips['max_page'])
print('{0} pages of trips to retrieve'.format(pages))

# Paginate through all pages and collect trip information
allPastTrips = []
for i in tqdm(range(1,pages+1)):
    response = requests.get('https://api.tripit.com/v1/list/trip/past/true/format/json/page_num/{0}'.format(i), auth=(USERNAME,PASSWORD))
    df = pd.json_normalize(response.json(),record_path=['Trip'])
    allPastTrips.append(df)
allPastTrips = pd.concat(allPastTrips,ignore_index=True)

# Convert dates
allPastTrips[['start_date','end_date']] = allPastTrips[['start_date','end_date']].apply(pd.to_datetime)

# Calculate days not present in USA (departure and return days not included as per:)
# https://www.uscis.gov/policy-manual/volume-12-part-d-chapter-4#
allPastTrips['non_present_days'] = (allPastTrips['end_date'] - allPastTrips['start_date'] - timedelta(days=1)).dt.days

# Account for same day trips
allPastTrips['non_present_days'].clip(lower=0,inplace=True)

# Filter to international trips
allPastInternationalTrips=allPastTrips.loc[allPastTrips['PrimaryLocationAddress.country'] !='US',['id','display_name','primary_location','PrimaryLocationAddress.country','start_date','end_date','non_present_days']]

# Write outputs to an Excel document
with pd.ExcelWriter('PastTrips.xlsx',engine='xlsxwriter') as writer:  
    allPastInternationalTrips.to_excel(writer, sheet_name='All Past International Trips')
    allPastTrips.to_excel(writer, sheet_name='All Past Trips')