import os, requests
import sys
import csv
import glob
import pathlib

def output_logger(fld):
    recent_dir = max(glob.glob(os.path.join(fld, '*/')), key=os.path.getmtime)
    recent_dir = max(glob.glob(os.path.join(recent_dir, '*/')), key=os.path.getmtime)
    action_files = glob.glob(os.path.join(recent_dir, 'world_1/action*'))
    if action_files:
        action_file = action_files[0]
    else:
        print(f"No action files found in {os.path.join(recent_dir, 'world_1')}")
        return
    action_header = []
    action_contents=[]
    trustfile_header = []
    trustfile_contents = []
    # Calculate the unique human and agent actions
    unique_agent_actions = []
    unique_human_actions = []
    with open(action_file) as csvfile:
        reader = csv.reader(csvfile, delimiter=';', quotechar="'")
        for row in reader:
            if action_header==[]:
                action_header=row
                continue
            if row[2:4] not in unique_agent_actions and row[2]!="":
                unique_agent_actions.append(row[2:4])
            if row[4:6] not in unique_human_actions and row[4]!="":
                unique_human_actions.append(row[4:6])
            if row[4] == 'RemoveObjectTogether' or row[4] == 'CarryObjectTogether' or row[4] == 'DropObjectTogether':
                if row[4:6] not in unique_agent_actions:
                    unique_agent_actions.append(row[4:6])
            res = {action_header[i]: row[i] for i in range(len(action_header))}
            action_contents.append(res)

    with open(fld+'/beliefs/currentTrustBelief.csv') as csvfile:
        reader = csv.reader(csvfile, delimiter=';', quotechar="'")
        for row in reader:
            if trustfile_header==[]:
                trustfile_header=row
                continue
            if row:
                res = {trustfile_header[i] : row[i] for i in range(len(trustfile_header))}
                trustfile_contents.append(res)
    # Retrieve the stored trust belief values
    name = trustfile_contents[-1]['name']
    search_room_comp = trustfile_contents[-1]['search_room_comp']
    search_room_will = trustfile_contents[-1]['search_room_will']
    obstacle_removal_comp = trustfile_contents[-1]['obstacle_removal_comp']
    obstacle_removal_will = trustfile_contents[-1]['obstacle_removal_will']
    victim_loc_comp = trustfile_contents[-1]['victim_loc_comp']
    victim_loc_will = trustfile_contents[-1]['victim_loc_will']
    rescue_together_comp = trustfile_contents[-1]['rescue_together_comp']
    rescue_together_will = trustfile_contents[-1]['rescue_together_will']
    # clear current beliefs file
    clear_current_trust_beliefs(fld)
    # Retrieve the number of ticks to finish the task, score, and completeness
    no_ticks = action_contents[-1]['tick_nr']
    score = action_contents[-1]['score']
    completeness = action_contents[-1]['completeness']
    # Save the output as a csv file
    print("Saving output...")
    with open(os.path.join(recent_dir,'world_1/output.csv'),mode='w') as csv_file:
        csv_writer = csv.writer(csv_file, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        csv_writer.writerow(['completeness','score','no_ticks','agent_actions','human_actions'])
        csv_writer.writerow([completeness,score,no_ticks,len(unique_agent_actions),len(unique_human_actions)])
    with open(fld + '/beliefs/allTrustBeliefs.csv', mode='a+') as csv_file:
        csv_writer = csv.writer(csv_file, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        csv_writer.writerow([name,
                             search_room_comp, search_room_will,
                             obstacle_removal_comp, obstacle_removal_will,
                             victim_loc_comp, victim_loc_will,
                             rescue_together_comp, rescue_together_will,
                             ])

def clear_current_trust_beliefs(fld: str):
    trust_belief_file = os.path.join(fld, 'beliefs/currentTrustBelief.csv')

    if os.path.exists(trust_belief_file):
        with open(trust_belief_file, mode='w', newline='') as csv_file:
            csv_writer = csv.writer(csv_file, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            csv_writer.writerow([])  # Overwrite with an empty file
        print("Cleared currentTrustBelief.csv successfully.")
    else:
        print("No currentTrustBelief.csv file found.")
