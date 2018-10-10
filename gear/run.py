#!/usr/bin/env python

import os
import json
import shutil
import flywheel
import numpy as np
from datetime import datetime
from pprint import pprint as pp

# Parse a config file
def parse_config(config_json_file):
    """
    Take a config.json file, read and return the config object.
    """

    if not os.path.isfile(config_json_file):
        raise ValueError('No config file could be found!')

    # Read the config json file
    with open(config_json_file, 'r') as jsonfile:
        config = json.load(jsonfile)

    return config

def get_timestamp_delta(timestamp, reference, absolute_value=False):
    """
    Given two timestamps, calculate and return the delta in total seconds.
    By default the delta is returned in absolute value.
    """

    from datetime import datetime

    ts = datetime.utcfromtimestamp(timestamp)
    ref = datetime.utcfromtimestamp(reference)
    delta = ts - ref

    if absolute_value:
        return abs(delta.total_seconds())
    else:
        return delta.total_seconds()


def fLoc_data(config=None, out_dir='/flywheel/v0/output/'):

    # Get the container info from the config doc
    analysis_id = str(config['destination']['id'])

    # Get analy
    analysis = fw.get_analysis(analysis_id)

    # Get container type and id from
    parent_container_type = analysis['parent']['type']
    parent_container_id = analysis['parent']['id']

    # Get the parent session's ID
    if parent_container_type == 'session':
        parent_session_id = parent_container_id
    else:
        raise ValueError("Input parent must be a 'session'" )

    # Get the acquisitions for the session
    session = fw.get_session(parent_session_id)
    session_acquisitions = fw.get_session_acquisitions(parent_session_id)

    data_dir = os.path.join(out_dir, 'fLoc', session['label'])
    print('Data dir set to: %s' % (data_dir))
    if not os.path.isdir(data_dir):
        os.makedirs(data_dir)

    # Now get the full thing from the DB.
    session_acquisitions_full = []
    for s in session_acquisitions:
        session_acquisitions_full.append(fw.get_acquisition(s.id))


    # FIND PAR FILES AND ASSOCIATED NIFTI FILES
    input_files = []
    found_par_files = False
    for a in session_acquisitions_full:
        for f in a['files']:
            if f['name'].endswith('.par'):

                print('Found parfile = %s ' % f['name'])
                found_par_files = True

                # Find the nifti file in this acquisition and download
                nifti = [ x for x in a['files'] if x['type'] == 'nifti' ]
                if nifti and len(nifti) == 1:
                    nifti = nifti[0]
                    nifti_rename = f['name'].replace('.par', '.nii.gz')
                    this_input = {'parfile': f['name'],
                                  'nifti': nifti['name'],
                                  'nifti_out_name': nifti_rename,
                                  'acquisition_id': a['_id'],
                                  'label': a['label'],
                                  'timestamp': a['timestamp'].strftime('%Y-%m-%dT%H:%M:%S')}
                    input_files.append(this_input)
                    print('  Found associated nifti file = %s \n\tDownloading nifti as %s...' % (nifti['name'], nifti_rename))
                    fw.download_file_from_acquisition(a['_id'],
                                                      f['name'],
                                                      os.path.join(data_dir, f['name']))
                    fw.download_file_from_acquisition(a['_id'],
                                                      nifti['name'],
                                                      os.path.join(data_dir, nifti_rename))
                else:
                    print('No nifti file found to associate with the parfile!!!')

    if found_par_files == False:
        return None
    else:
        num_runs = len(input_files)


    # FIND IN-PLANE SCAN
    inplanes = []
    for a in session_acquisitions_full:
        for f in a['files']:
            if f['classification'] and f['classification'].has_key('Features') and 'In-Plane' in f['classification']['Features']:
                inplanes.append(a)

    if inplanes and len(inplanes) >1:
        print('More than one Inplane acquisition was found!!!')

    # Find the correct inplane when one or more exist, making the assumption that
    # the last inplane is the one we actually want to use.
    inplanes_sorted = sorted(inplanes, key=lambda k: k['timestamp'])
    inplane = inplanes_sorted[-1]
    nifti = [ x for x in inplane['files'] if x['type'] == 'nifti' ]
    if nifti and len(nifti) == 1:
        nifti = nifti[0]
        nifti_rename = 'Inplane.nii.gz'
        this_input = {'nifti': nifti['name'],
                      'nifti_out_name': nifti_rename,
                      'acquisition_id': inplane['_id'],
                      'label': inplane['label'],
                      'timestamp': inplane['timestamp'].strftime('%Y-%m-%dT%H:%M:%S')}
        input_files.append(this_input)
        print('Found associated inplane file = %s \n\tDownloading nifti as %s...' % (nifti['name'], nifti_rename))
        fw.download_file_from_acquisition(inplane['_id'],
                                          nifti['name'],
                                          os.path.join(data_dir, nifti_rename))

    # TRACK INPUTS AND WRITE TO FILE
    inputs = {  "session_id": parent_session_id,
                "session_label":session['label'],
                "num_runs": str(num_runs),
                "files": input_files
                }

    # Write out the json file with input files
    json_file = os.path.join(out_dir, 'input_data.json')
    with open(json_file, 'w') as jf:
        json.dump(inputs, jf)


    return inputs, data_dir


###############################################################################
# MAIN

if __name__ == '__main__':

    import urllib3
    urllib3.disable_warnings()
    os.environ['FLYWHEEL_SDK_SKIP_VERSION_CHECK'] = '1'

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--config_file',
                    type=str,
                    dest="config_file",
                    default='/flywheel/v0/config.json',
                    help='Full path to the input json config file.')
    ap.add_argument('--output_dir',
                    type=str,
                    dest="output_dir",
                    default='/flywheel/v0/output',
                    help='Directory in which to save the results.')

    args = ap.parse_args()

    # Load/Parse the configuration file
    config = parse_config(args.config_file)

    # Create SDK client
    print('  Creating SDK client...')
    fw = flywheel.Flywheel(config['inputs']['api_key']['key'])

    # Download fLOC data
    print('Gathering fLOC Data in %s...' % (args.output_dir))
    input_files, data_dir = fLoc_data(config, args.output_dir)

    if not input_files:
        print('Errors finding input files...')
        os.sys.exit(1)

    # RUN MATLAB CODE
    run_command = '%s %s %s %s' % (matlab_binary, matlab_library, data_dir, args.config_file)
    os.system(run_command)

    # COMPRESS OUTPUTS (preserve the config/json/log files at the top-level?)
    # The results come in a deeply nested directory tree, thus we want to compress the outputs so that they are easy to work withself.

    # Preserve the directory tree in json format for easy navigation outside of the platform. - Package list for the zip file.


    # EXIT
