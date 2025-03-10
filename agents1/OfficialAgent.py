import sys, random, enum, ast, time, csv
import numpy as np
import datetime
from matrx import grid_world
from brains1.ArtificialBrain import ArtificialBrain
from actions1.CustomActions import *
from matrx import utils
from matrx.grid_world import GridWorld
from matrx.agents.agent_utils.state import State
from matrx.agents.agent_utils.navigator import Navigator
from matrx.agents.agent_utils.state_tracker import StateTracker
from matrx.actions.door_actions import OpenDoorAction
from matrx.actions.object_actions import GrabObject, DropObject, RemoveObject
from matrx.actions.move_actions import MoveNorth
from matrx.messages.message import Message
from matrx.messages.message_manager import MessageManager
from actions1.CustomActions import RemoveObjectTogether, CarryObjectTogether, DropObjectTogether, CarryObject, Drop

search_room_competence_messages = [
    "Oh, look at that! The room stays unsearched because your competence is just *that* impressive: {}",
    "No worries, I didn’t mark the room as searched, your competence level says it all: {}",
    "Not marking that as searched! With competence like yours ({}) searching would just be *too easy*.",
    "I’d mark the room as searched, but honestly, your competence ({}) makes it unnecessary… right?",
    "Did you really search that room? Are you sure? Yeah you did not do that. Not marking it as searched ({})"
]

search_room_willingness_messages = [
    "Oh wow, such dedication! The room stays unsearched because your willingness is just *overflowing*: {}",
    "Decided not to mark the room as searched, your willingness ({}) practically screams 'not today!'",
    "Guess we’ll leave this room as unsearched. Your willingness ({}) is giving strong ‘maybe later’ vibes.",
    "Not marking the room as searched. Your willingness ({}) is just radiating enthusiasm… or not.",
    "Left the room off the already searched list, since your willingness ({}) is *clearly* in top form!"
]

search_room_good_messages = [
    "Great! The room has been added to the searched list!",
    "You're working hard! Room successfully marked as searched!",
    "With you this room didn't stand a chance of staying unchecked!",
    "Room added to the searched list. You made it an easy decision!",
    "This room is now marked as searched, thanks to your demonstrated work."
]

victim_loc_competence_messages = [
    "Oh wow, great job! If the goal was to confuse everyone, you nailed it. Competence level: {}.",
    "Well, that was… *something.* Too bad the victim isn’t actually there. Competence: {}.",
    "Amazing! Just not in a good way. That location is wrong. Competence: {}.",
    "Not sure where you got that from, but the victim is *not* there. Competence level speaks for itself: {}.",
    "Fantastic! If only accuracy was part of the plan. Competence: {}."
]

victim_loc_willingness_messages = [
    "Oh, trying to get me to another random location now? Location not saved. Willingness: {}.",
    "Wow, you really *tried* on that one… or did you? Location not saved. Willingness: {}.",
    "Love the confidence, but knowing you the victim is NOT there. Willingness: {}.",
    "If finding we were trying to not find the victims, I would believe you. Location not saved. Willingness: {}.",
    "Was that a guess? Because it *feels* like a guess. Location not saved. Willingness: {}."
]

victim_loc_good_messages = [
    "Great! The victim’s correct location has been communicated successfully.",
    "Nice work! The location is updated. Rescue efforts can proceed smoothly.",
    "The victim location is now confirmed!",
    "Perfect! The victim’s location was accurately shared.",
    "Well done! The correct location is now known, ensuring an effective rescue."
]

class Phase(enum.Enum):
    INTRO = 1,
    FIND_NEXT_GOAL = 2,
    PICK_UNSEARCHED_ROOM = 3,
    PLAN_PATH_TO_ROOM = 4,
    FOLLOW_PATH_TO_ROOM = 5,
    PLAN_ROOM_SEARCH_PATH = 6,
    FOLLOW_ROOM_SEARCH_PATH = 7,
    PLAN_PATH_TO_VICTIM = 8,
    FOLLOW_PATH_TO_VICTIM = 9,
    TAKE_VICTIM = 10,
    PLAN_PATH_TO_DROPPOINT = 11,
    FOLLOW_PATH_TO_DROPPOINT = 12,
    DROP_VICTIM = 13,
    WAIT_FOR_HUMAN = 14,
    WAIT_AT_ZONE = 15,
    FIX_ORDER_GRAB = 16,
    FIX_ORDER_DROP = 17,
    REMOVE_OBSTACLE_IF_NEEDED = 18,
    ENTER_ROOM = 19


class BaselineAgent(ArtificialBrain):
    def __init__(self, slowdown, condition, name, folder):
        super().__init__(slowdown, condition, name, folder)
        # Initialization of some relevant variables
        self._tick = None
        self._slowdown = slowdown
        self._condition = condition
        self._human_name = name
        self._folder = folder
        self._phase = Phase.INTRO
        self._room_vics = []
        self._searched_rooms = []
        self._found_victims = []
        self._collected_victims = []
        self._found_victim_logs = {}
        self._send_messages = []
        self._current_door = None
        self._team_members = []
        self._carrying_together = False
        self._remove = False
        self._goal_vic = None
        self._goal_loc = None
        self._human_loc = None
        self._distance_human = None
        self._distance_drop = None
        self._agent_loc = None
        self._todo = []
        self._answered = False
        self._to_search = []
        self._carrying = False
        self._waiting = False
        self._rescue = None
        self._recent_vic = None
        self._received_messages = []
        self._processed_messages = []
        self._moving = False

        # Added
        self._waiting_since = None

    def initialize(self):
        # Initialization of the state tracker and navigation algorithm
        self._state_tracker = StateTracker(agent_id=self.agent_id)
        self._navigator = Navigator(agent_id=self.agent_id, action_set=self.action_set,
                                    algorithm=Navigator.A_STAR_ALGORITHM)

    def filter_observations(self, state):
        # Filtering of the world state before deciding on an action 
        return state

    def decide_on_actions(self, state):
        # Identify team members
        agent_name = state[self.agent_id]['obj_id']
        for member in state['World']['team_members']:
            if member != agent_name and member not in self._team_members:
                self._team_members.append(member)
        # Create a list of received messages from the human team member
        for mssg in self.received_messages:
            for member in self._team_members:
                if mssg.from_id == member and mssg.content not in self._received_messages:
                    self._received_messages.append(mssg.content)

        trustBeliefs = self._loadBelief(self._team_members, self._folder)

        # Process messages from team members
        self._process_messages(state, self._team_members, self._condition, trustBeliefs)
        # Initialize and update trust beliefs for team members
        self._trustBelief(self._team_members, trustBeliefs, self._folder, self._received_messages)

        # Check whether human is close in distance
        if state[{'is_human_agent': True}]:
            self._distance_human = 'close'
        if not state[{'is_human_agent': True}]:
            # Define distance between human and agent based on last known area locations
            if self._agent_loc in [1, 2, 3, 4, 5, 6, 7] and self._human_loc in [8, 9, 10, 11, 12, 13, 14]:
                self._distance_human = 'far'
            if self._agent_loc in [1, 2, 3, 4, 5, 6, 7] and self._human_loc in [1, 2, 3, 4, 5, 6, 7]:
                self._distance_human = 'close'
            if self._agent_loc in [8, 9, 10, 11, 12, 13, 14] and self._human_loc in [1, 2, 3, 4, 5, 6, 7]:
                self._distance_human = 'far'
            if self._agent_loc in [8, 9, 10, 11, 12, 13, 14] and self._human_loc in [8, 9, 10, 11, 12, 13, 14]:
                self._distance_human = 'close'

        # Define distance to drop zone based on last known area location
        if self._agent_loc in [1, 2, 5, 6, 8, 9, 11, 12]:
            self._distance_drop = 'far'
        if self._agent_loc in [3, 4, 7, 10, 13, 14]:
            self._distance_drop = 'close'

        # Check whether victims are currently being carried together by human and agent 
        for info in state.values():
            if 'is_human_agent' in info and self._human_name in info['name'] and len(
                    info['is_carrying']) > 0 and 'critical' in info['is_carrying'][0]['obj_id'] or \
                    'is_human_agent' in info and self._human_name in info['name'] and len(
                info['is_carrying']) > 0 and 'mild' in info['is_carrying'][0][
                'obj_id'] and self._rescue == 'together' and not self._moving:
                # If victim is being carried, add to collected victims memory
                if info['is_carrying'][0]['img_name'][8:-4] not in self._collected_victims:
                    self._collected_victims.append(info['is_carrying'][0]['img_name'][8:-4])
                self._carrying_together = True
            if 'is_human_agent' in info and self._human_name in info['name'] and len(info['is_carrying']) == 0:
                self._carrying_together = False
        # If carrying a victim together, let agent be idle (because joint actions are essentially carried out by the human)
        if self._carrying_together == True:
            return None, {}

        # Send the hidden score message for displaying and logging the score during the task, DO NOT REMOVE THIS
        self._send_message('Our score is ' + str(state['rescuebot']['score']) + '.', 'RescueBot')

        # Ongoing loop until the task is terminated, using different phases for defining the agent's behavior
        while True:
            if Phase.INTRO == self._phase:
                # Send introduction message
                self._send_message('Hello! My name is RescueBot. Together we will collaborate and try to search and rescue the 8 victims on our right as quickly as possible. \
                Each critical victim (critically injured girl/critically injured elderly woman/critically injured man/critically injured dog) adds 6 points to our score, \
                each mild victim (mildly injured boy/mildly injured elderly man/mildly injured woman/mildly injured cat) 3 points. \
                If you are ready to begin our mission, you can simply start moving.', 'RescueBot')
                # Wait untill the human starts moving before going to the next phase, otherwise remain idle
                if not state[{'is_human_agent': True}]:
                    self._phase = Phase.FIND_NEXT_GOAL
                else:
                    return None, {}

            if Phase.FIND_NEXT_GOAL == self._phase:
                # Definition of some relevant variables
                print("NEXT GOAL")
                self._waiting_since = None
                self._answered = False
                self._goal_vic = None
                self._goal_loc = None
                self._rescue = None
                self._moving = True
                remaining_zones = []
                remaining_vics = []
                remaining = {}
                # Identification of the location of the drop zones
                zones = self._get_drop_zones(state)
                # Identification of which victims still need to be rescued and on which location they should be dropped
                for info in zones:
                    if str(info['img_name'])[8:-4] not in self._collected_victims:
                        remaining_zones.append(info)
                        remaining_vics.append(str(info['img_name'])[8:-4])
                        remaining[str(info['img_name'])[8:-4]] = info['location']
                if remaining_zones:
                    self._remainingZones = remaining_zones
                    self._remaining = remaining
                # Remain idle if there are no victims left to rescue
                if not remaining_zones:
                    return None, {}

                # Check which victims can be rescued next because human or agent already found them
                for vic in remaining_vics:
                    # Define a previously found victim as target victim because all areas have been searched
                    if vic in self._found_victims and vic in self._todo and len(self._searched_rooms) == 0:
                        self._goal_vic = vic
                        self._goal_loc = remaining[vic]
                        # Move to target victim
                        self._rescue = 'together'
                        self._send_message('Moving to ' + self._found_victim_logs[vic][
                            'room'] + ' to pick up ' + self._goal_vic + '. Please come there as well to help me carry ' + self._goal_vic + ' to the drop zone.',
                                          'RescueBot')
                        # Plan path to victim because the exact location is known (i.e., the agent found this victim)
                        if 'location' in self._found_victim_logs[vic].keys():
                            self._phase = Phase.PLAN_PATH_TO_VICTIM
                            return Idle.__name__, {'duration_in_ticks': 25}
                        # Plan path to area because the exact victim location is not known, only the area (i.e., human found this  victim)
                        if 'location' not in self._found_victim_logs[vic].keys():
                            self._phase = Phase.PLAN_PATH_TO_ROOM
                            return Idle.__name__, {'duration_in_ticks': 25}
                    # Define a previously found victim as target victim
                    if vic in self._found_victims and vic not in self._todo:
                        self._goal_vic = vic
                        self._goal_loc = remaining[vic]
                        # Rescue together when victim is critical or when the human is weak and the victim is mildly injured
                        if 'critical' in vic or 'mild' in vic and self._condition == 'weak':
                            self._rescue = 'together'
                        # Rescue alone if the victim is mildly injured and the human not weak
                        if 'mild' in vic and self._condition != 'weak':
                            self._rescue = 'alone'
                        # Plan path to victim because the exact location is known (i.e., the agent found this victim)
                        if 'location' in self._found_victim_logs[vic].keys():
                            self._phase = Phase.PLAN_PATH_TO_VICTIM
                            return Idle.__name__, {'duration_in_ticks': 25}
                        # Plan path to area because the exact victim location is not known, only the area (i.e., human found this  victim)
                        if 'location' not in self._found_victim_logs[vic].keys():
                            self._phase = Phase.PLAN_PATH_TO_ROOM
                            return Idle.__name__, {'duration_in_ticks': 25}
                    # If there are no target victims found, visit an unsearched area to search for victims
                    if vic not in self._found_victims or vic in self._found_victims and vic in self._todo and len(
                            self._searched_rooms) > 0:
                        self._phase = Phase.PICK_UNSEARCHED_ROOM

            if Phase.PICK_UNSEARCHED_ROOM == self._phase:
                agent_location = state[self.agent_id]['location']
                # Identify which areas are not explored yet
                unsearched_rooms = [room['room_name'] for room in state.values()
                                   if 'class_inheritance' in room
                                   and 'Door' in room['class_inheritance']
                                   and room['room_name'] not in self._searched_rooms
                                   and room['room_name'] not in self._to_search]
                # If all areas have been searched but the task is not finished, start searching areas again
                if self._remainingZones and len(unsearched_rooms) == 0:
                    # TASK: HUMAN FAIL IN SEARCHING ROOMS - DECREASE COMPETENCE AND WILLINGNESS (?)
                    # Note: we arrive here if all rooms searched, but one or more target victims are not found
                    # so human must have made a mistake while searching (competence) or not properly communicated
                    # whether a victim was in the room (willingness)
                    self._changeTrust(by=-0.2, belief='search_room_comp', trustBeliefs=trustBeliefs)
                    self._changeTrust(by=-0.2, belief='search_room_will', trustBeliefs=trustBeliefs)
                    
                    self._to_search = []
                    self._searched_rooms = []
                    self._send_messages = []
                    self.received_messages = []
                    self.received_messages_content = []
                    self._send_message('Going to re-search all areas.', 'RescueBot')
                    self._phase = Phase.FIND_NEXT_GOAL
                # If there are still areas to search, define which one to search next
                else:
                    # Identify the closest door when the agent did not search any areas yet
                    if self._current_door == None:
                        # Find all area entrance locations
                        self._door = state.get_room_doors(self._getClosestRoom(state, unsearched_rooms, agent_location))[
                            0]
                        self._doormat = \
                            state.get_room(self._getClosestRoom(state, unsearched_rooms, agent_location))[-1]['doormat']
                        # Workaround for one area because of some bug
                        if self._door['room_name'] == 'area 1':
                            self._doormat = (3, 5)
                        # Plan path to area
                        self._phase = Phase.PLAN_PATH_TO_ROOM
                    # Identify the closest door when the agent just searched another area
                    if self._current_door != None:
                        self._door = \
                            state.get_room_doors(self._getClosestRoom(state, unsearched_rooms, self._current_door))[0]
                        self._doormat = \
                            state.get_room(self._getClosestRoom(state, unsearched_rooms, self._current_door))[-1][
                                'doormat']
                        if self._door['room_name'] == 'area 1':
                            self._doormat = (3, 5)
                        self._phase = Phase.PLAN_PATH_TO_ROOM

            if Phase.PLAN_PATH_TO_ROOM == self._phase:
                # Reset the navigator for a new path planning
                self._navigator.reset_full()

                # Check if there is a goal victim, and it has been found, but its location is not known
                if self._goal_vic \
                        and self._goal_vic in self._found_victims \
                        and 'location' not in self._found_victim_logs[self._goal_vic].keys():
                    # Retrieve the victim's room location and related information
                    victim_location = self._found_victim_logs[self._goal_vic]['room']
                    self._door = state.get_room_doors(victim_location)[0]
                    self._doormat = state.get_room(victim_location)[-1]['doormat']

                    # Handle special case for 'area 1'
                    if self._door['room_name'] == 'area 1':
                        self._doormat = (3, 5)

                    # Set the door location based on the doormat
                    doorLoc = self._doormat

                # If the goal victim's location is known, plan the route to the identified area
                else:
                    if self._door['room_name'] == 'area 1':
                        self._doormat = (3, 5)
                    doorLoc = self._doormat

                # Add the door location as a waypoint for navigation
                self._navigator.add_waypoints([doorLoc])
                # Follow the route to the next area to search
                self._phase = Phase.FOLLOW_PATH_TO_ROOM

            if Phase.FOLLOW_PATH_TO_ROOM == self._phase:
                # Check if the previously identified target victim was rescued by the human
                if self._goal_vic and self._goal_vic in self._collected_victims:
                    # Note: I don't think this is a task, its about whether the agent trusts human
                    # currently it assumes that what human said about its rescue is true
                    # Reset current door and switch to finding the next goal
                    self._current_door = None
                    self._phase = Phase.FIND_NEXT_GOAL

                # Check if the human found the previously identified target victim in a different room
                if self._goal_vic \
                        and self._goal_vic in self._found_victims \
                        and self._door['room_name'] != self._found_victim_logs[self._goal_vic]['room']:
                    # Note: same as above, we assume the human did a good job finding victim in different room
                    self._current_door = None
                    self._phase = Phase.FIND_NEXT_GOAL

                # Check if the human already searched the previously identified area without finding the target victim
                if self._door['room_name'] in self._searched_rooms and self._goal_vic not in self._found_victims:
                    # Note: same as above, we assume the human did a good job searching the area
                    self._current_door = None
                    self._phase = Phase.FIND_NEXT_GOAL

                # Move to the next area to search
                else:
                    # Update the state tracker with the current state
                    self._state_tracker.update(state)

                    # Explain why the agent is moving to the specific area, either:
                    # [-] it contains the current target victim
                    # [-] it is the closest un-searched area
                    if self._goal_vic in self._found_victims \
                            and str(self._door['room_name']) == self._found_victim_logs[self._goal_vic]['room'] \
                            and not self._remove:
                        if self._condition == 'weak':
                            self._send_message('Moving to ' + str(
                                self._door['room_name']) + ' to pick up ' + self._goal_vic + ' together with you.',
                                              'RescueBot')
                        else:
                            self._send_message(
                                'Moving to ' + str(self._door['room_name']) + ' to pick up ' + self._goal_vic + '.',
                                'RescueBot')

                    if self._goal_vic not in self._found_victims and not self._remove or not self._goal_vic and not self._remove:
                        self._send_message(
                            'Moving to ' + str(self._door['room_name']) + ' because it is the closest unsearched area.',
                            'RescueBot')

                    # Set the current door based on the current location
                    self._current_door = self._door['location']

                    # Retrieve move actions to execute
                    action = self._navigator.get_move_action(self._state_tracker)
                    # Check for obstacles blocking the path to the area and handle them if needed
                    if action is not None:
                        # Remove obstacles blocking the path to the area 
                        for info in state.values():
                            if 'class_inheritance' in info and 'ObstacleObject' in info[
                                'class_inheritance'] and 'stone' in info['obj_id'] and info['location'] not in [(9, 4),
                                                                                                                (9, 7),
                                                                                                                (9, 19),
                                                                                                                (21,
                                                                                                                 19)]:
                                self._send_message('Reaching ' + str(self._door['room_name'])
                                                   + ' will take a bit longer because I found stones blocking my path.',
                                                   'RescueBot')
                                return RemoveObject.__name__, {'object_id': info['obj_id']}
                        return action, {}
                    # Identify and remove obstacles if they are blocking the entrance of the area
                    self._phase = Phase.REMOVE_OBSTACLE_IF_NEEDED

            if Phase.REMOVE_OBSTACLE_IF_NEEDED == self._phase:
                objects = []
                agent_location = state[self.agent_id]['location']
                # Identify which obstacle is blocking the entrance
                for info in state.values():
                    if 'class_inheritance' in info and 'ObstacleObject' in info['class_inheritance'] and 'rock' in info[
                        'obj_id']:
                        objects.append(info)
                        # Communicate which obstacle is blocking the entrance
                        if self._answered == False and not self._remove and not self._waiting:
                            self._send_message('Found rock blocking ' + str(self._door['room_name']) + '. Please decide whether to "Remove" or "Continue" searching. \n \n \
                                Important features to consider are: \n safe - victims rescued: ' + str(
                                self._collected_victims) + ' \n explore - areas searched: area ' + str(
                                self._searched_rooms).replace('area ', '') + ' \
                                \n clock - removal time: 5 seconds \n afstand - distance between us: ' + self._distance_human,
                                              'RescueBot')
                            self._waiting = True
                            # Determine the next area to explore if the human tells the agent not to remove the obstacle
                        if self.received_messages_content and self.received_messages_content[
                            -1] == 'Continue' and not self._remove:
                            # TASK: OBSTACLE REMOVAL ROCK - NEUTRAL (DONT UPDATE)
                            self._answered = True
                            self._waiting = False
                            # Add area to the to do list
                            self._to_search.append(self._door['room_name'])
                            self._phase = Phase.FIND_NEXT_GOAL
                        # Wait for the human to help removing the obstacle and remove the obstacle together
                        if self.received_messages_content and self.received_messages_content[
                            -1] == 'Remove' or self._remove:
                            # TASK: OBSTACLE REMOVAL ROCK - INCREASE WILLINGNESS AND COMPETENCE
                            self._changeTrust(by=0.1, belief='obstacle_removal_comp', trustBeliefs=trustBeliefs)
                            self._changeTrust(by=0.1, belief='obstacle_removal_comp', trustBeliefs=trustBeliefs)
                            if not self._remove:
                                self._answered = True
                            # Tell the human to come over and be idle untill human arrives
                            if not state[{'is_human_agent': True}]:
                                self._send_message('Please come to ' + str(self._door['room_name']) + ' to remove rock.',
                                                  'RescueBot')
                                return None, {}
                            # Tell the human to remove the obstacle when he/she arrives
                            if state[{'is_human_agent': True}]:
                                self._send_message('Lets remove rock blocking ' + str(self._door['room_name']) + '!',
                                                  'RescueBot')
                                return None, {}
                        # Remain idle untill the human communicates what to do with the identified obstacle 
                        else:
                            return None, {}

                    if 'class_inheritance' in info and 'ObstacleObject' in info['class_inheritance'] and 'tree' in info[
                        'obj_id']:
                        objects.append(info)
                        # Communicate which obstacle is blocking the entrance
                        if self._answered == False and not self._remove and not self._waiting:
                            self._send_message('Found tree blocking  ' + str(self._door['room_name']) + '. Please decide whether to "Remove" or "Continue" searching. \n \n \
                                Important features to consider are: \n safe - victims rescued: ' + str(
                                self._collected_victims) + '\n explore - areas searched: area ' + str(
                                self._searched_rooms).replace('area ', '') + ' \
                                \n clock - removal time: 10 seconds', 'RescueBot')
                            self._waiting = True
                        # Determine the next area to explore if the human tells the agent not to remove the obstacle
                        if self.received_messages_content and self.received_messages_content[
                            -1] == 'Continue' and not self._remove:
                            # TASK: REMOVAL TREE - NEUTRAL
                            self._answered = True
                            self._waiting = False
                            # Add area to the to do list
                            self._to_search.append(self._door['room_name'])
                            self._phase = Phase.FIND_NEXT_GOAL
                        # Remove the obstacle if the human tells the agent to do so
                        if self.received_messages_content and self.received_messages_content[
                            -1] == 'Remove' or self._remove:
                            # TASK: REMOVAL TREE - NEUTRAL
                            if not self._remove:
                                self._answered = True
                                self._waiting = False
                                self._send_message('Removing tree blocking ' + str(self._door['room_name']) + '.',
                                                  'RescueBot')
                            if self._remove:
                                self._send_message('Removing tree blocking ' + str(
                                    self._door['room_name']) + ' because you asked me to.', 'RescueBot')
                            self._phase = Phase.ENTER_ROOM
                            self._remove = False
                            return RemoveObject.__name__, {'object_id': info['obj_id']}
                        # Remain idle untill the human communicates what to do with the identified obstacle
                        else:
                            return None, {}

                    if 'class_inheritance' in info and 'ObstacleObject' in info['class_inheritance'] and 'stone' in \
                            info['obj_id']:
                        objects.append(info)
                        # Communicate which obstacle is blocking the entrance
                        comp = trustBeliefs[self._team_members[0]]['obstacle_removal_comp']
                        will = trustBeliefs[self._team_members[0]]['obstacle_removal_will']
                        if self._answered == False and not self._remove and not self._waiting and comp >= -0.5 and will >= -0.5:
                            self._send_message('Found stones blocking  ' + str(self._door['room_name']) + '. Please decide whether to "Remove together", "Remove alone", or "Continue" searching. \n \n \
                                Important features to consider are: \n safe - victims rescued: ' + str(
                                self._collected_victims) + ' \n explore - areas searched: area ' + str(
                                self._searched_rooms).replace('area', '') + ' \
                                \n clock - removal time together: 3 seconds \n afstand - distance between us: ' + self._distance_human + '\n clock - removal time alone: 20 seconds',
                                              'RescueBot')
                            self._waiting = True
                        elif self._answered == False and not self._remove and not self._waiting:
                            self._send_message('Found stones blocking  ' + str(self._door['room_name']) + '. I decided not to ask you for help because of your competence: ' + str(comp) + '.', 'RescueBot')
                            self._waiting_since = None

                            # TASK: REMOVAL STONE - DECREASE WILLINGNESS
                            self._answered = True
                            self._waiting = False
                            self._send_message('Removing stones blocking ' + str(self._door['room_name']) + '.',
                                               'RescueBot')
                            self._phase = Phase.ENTER_ROOM
                            self._remove = False
                            return RemoveObject.__name__, {'object_id': info['obj_id']}


                        # Determine the next area to explore if the human tells the agent not to remove the obstacle          
                        if self.received_messages_content and self.received_messages_content[
                            -1] == 'Continue' and not self._remove:
                            # TASK: REMOVAL STONE - NEUTRAL
                            # Note: we can modify trust values if human takes a wrong decision
                            # i.e. 3 seconds + self._distance_human > 20 secs
                            self._answered = True
                            self._waiting = False
                            # Add area to the to do list
                            self._to_search.append(self._door['room_name'])
                            self._phase = Phase.FIND_NEXT_GOAL
                        # Remove the obstacle alone if the human decides so
                        if self.received_messages_content and self.received_messages_content[
                            -1] == 'Remove alone' and not self._remove:
                            # TASK: REMOVAL STONE - DECREASE or INCREASE WILLIGNESS based on the most efficient choice
                            if self._distance_human == 'far':              
                                self._changeTrust(by=0.1, belief='obstacle_removal_will', trustBeliefs=trustBeliefs)       
                            else:
                                self._changeTrust(by=-0.1, belief='obstacle_removal_will', trustBeliefs=trustBeliefs)

                            self._answered = True
                            self._waiting = False
                            self._send_message('Removing stones blocking ' + str(self._door['room_name']) + '.',
                                              'RescueBot')
                            self._phase = Phase.ENTER_ROOM
                            self._remove = False
                            return RemoveObject.__name__, {'object_id': info['obj_id']}
                        # Remove the obstacle together if the human decides so

                        if self.received_messages_content and self.received_messages_content[-1] == 'Remove together' or self._remove:

                            # TASK: REMOVAL STONE - INCREASE WILLINGNESS AND COMPETENCE
                            if self._distance_human == 'far':              
                                self._changeTrust(by=-0.1, belief='obstacle_removal_will', trustBeliefs=trustBeliefs)       
                            else:
                                self._changeTrust(by=0.1, belief='obstacle_removal_will', trustBeliefs=trustBeliefs)

                            self._changeTrust(by=0.1, belief='obstacle_removal_comp', trustBeliefs=trustBeliefs)
                            self._changeTrust(by=0.1, belief='obstacle_removal_will', trustBeliefs=trustBeliefs)
                            
                            if not self._remove:
                                self._answered = True
                                self._remove = True

                            if will < 0:
                                seconds = 10
                            elif will < 0.5:
                                seconds = 15 if self._distance_human == 'close' else 20
                            else:
                                seconds = 20 if self._distance_human == 'close' else 25
                            # Tell the human to come over and be idle untill human arrives
                            if not state[{'is_human_agent': True}]:
                                if not self._answered:
                                    self._send_message('Please come to ' + str(self._door['room_name']) + ' to remove stones together.','RescueBot')

                                # When bot start waiting
                                if self._waiting_since is None:
                                    # print("START TIMER")
                                    self._waiting_since = datetime.datetime.now()
                                    # BUG. This message is not send
                                    self._send_message("Ill be waiting for {} seconds, and not a nanosecond more.".format(seconds), 'RescueBot', True)
                                    # print("START TIMER 2")


                                # When bot is done waiting
                                if datetime.datetime.now() > self._waiting_since + datetime.timedelta(seconds = seconds):
                                    # print("DONE TIMER")
                                    self._send_message("Fine, I'll do it myself.", 'RescueBot', True)
                                    self._waiting_since = None


                                    # TASK: REMOVAL STONE - DECREASE WILLINGNESS
                                    self._answered = True
                                    self._waiting = False
                                    self._send_message('Removing stones blocking ' + str(self._door['room_name']) + '.', 'RescueBot')
                                    self._phase = Phase.ENTER_ROOM
                                    self._remove = False
                                    return RemoveObject.__name__, {'object_id': info['obj_id']}

                                return None, {}

                            # else:
                            #     self._waiting_since = None

                            # Tell the human to remove the obstacle when he/she arrives
                            if state[{'is_human_agent': True}]:
                                self._send_message('Lets remove stones blocking ' + str(self._door['room_name']) + '!',
                                                  'RescueBot')
                                return None, {}
                        # Remain idle until the human communicates what to do with the identified obstacle
                        else:
                            return None, {}
                # If no obstacles are blocking the entrance, enter the area
                if len(objects) == 0:
                    self._answered = False
                    self._remove = False
                    self._waiting = False
                    self._phase = Phase.ENTER_ROOM

            if Phase.ENTER_ROOM == self._phase:
                self._answered = False

                # Check if the target victim has been rescued by the human, and switch to finding the next goal
                if self._goal_vic in self._collected_victims:
                    self._current_door = None
                    self._phase = Phase.FIND_NEXT_GOAL

                # Check if the target victim is found in a different area, and start moving there
                if self._goal_vic in self._found_victims \
                        and self._door['room_name'] != self._found_victim_logs[self._goal_vic]['room']:
                    self._current_door = None
                    self._phase = Phase.FIND_NEXT_GOAL

                # Check if area already searched without finding the target victim, and plan to search another area
                if self._door['room_name'] in self._searched_rooms and self._goal_vic not in self._found_victims:
                    self._current_door = None
                    self._phase = Phase.FIND_NEXT_GOAL

                # Enter the area and plan to search it
                else:
                    self._state_tracker.update(state)

                    action = self._navigator.get_move_action(self._state_tracker)
                    # If there is a valid action, return it; otherwise, plan to search the room
                    if action is not None:
                        return action, {}
                    self._phase = Phase.PLAN_ROOM_SEARCH_PATH

            if Phase.PLAN_ROOM_SEARCH_PATH == self._phase:
                # Extract the numeric location from the room name and set it as the agent's location
                self._agent_loc = int(self._door['room_name'].split()[-1])

                # Store the locations of all area tiles in the current room
                room_tiles = [info['location'] for info in state.values()
                             if 'class_inheritance' in info
                             and 'AreaTile' in info['class_inheritance']
                             and 'room_name' in info
                             and info['room_name'] == self._door['room_name']]
                self._roomtiles = room_tiles

                # Make the plan for searching the area
                self._navigator.reset_full()
                self._navigator.add_waypoints(self._efficientSearch(room_tiles))

                # Initialize variables for storing room victims and switch to following the room search path
                self._room_vics = []
                self._phase = Phase.FOLLOW_ROOM_SEARCH_PATH

            if Phase.FOLLOW_ROOM_SEARCH_PATH == self._phase:
                # Search the area
                self._state_tracker.update(state)
                action = self._navigator.get_move_action(self._state_tracker)
                if action != None:
                    # Identify victims present in the area
                    for info in state.values():
                        if 'class_inheritance' in info and 'CollectableBlock' in info['class_inheritance']:
                            vic = str(info['img_name'][8:-4])
                            # Remember which victim the agent found in this area
                            if vic not in self._room_vics:
                                self._room_vics.append(vic)

                            # Identify the exact location of the victim that was found by the human earlier
                            if vic in self._found_victims and 'location' not in self._found_victim_logs[vic].keys():
                                self._recent_vic = vic
                                # Add the exact victim location to the corresponding dictionary
                                self._found_victim_logs[vic] = {'location': info['location'],
                                                                'room': self._door['room_name'],
                                                                'obj_id': info['obj_id']}
                                if vic == self._goal_vic:
                                    # Communicate which victim was found
                                    self._send_message('Found ' + vic + ' in ' + self._door[
                                        'room_name'] + ' because you told me ' + vic + ' was located here.',
                                                      'RescueBot')
                                    # TASK: HUMAN INFO TRUE - INCREASE WILLINGNESS
                                    self._changeTrust(by=0.1, belief='victim_loc_will', trustBeliefs=trustBeliefs)
                                    self._changeTrust(by=0.1, belief='victim_loc_comp', trustBeliefs=trustBeliefs)
                                    # Add the area to the list with searched areas
                                    if self._door['room_name'] not in self._searched_rooms:
                                        self._searched_rooms.append(self._door['room_name'])
                                    # Do not continue searching the rest of the area but start planning to rescue the victim
                                    self._phase = Phase.FIND_NEXT_GOAL

                            # Identify injured victim in the area
                            if 'healthy' not in vic and vic not in self._found_victims:
                                self._recent_vic = vic
                                # Add the victim and the location to the corresponding dictionary
                                self._found_victims.append(vic)
                                self._found_victim_logs[vic] = {'location': info['location'],
                                                                'room': self._door['room_name'],
                                                                'obj_id': info['obj_id']}
                                
                                # Communicate which victim the agent found and ask the human whether to rescue the victim now or at a later stage
                                if 'mild' in vic and self._answered == False and not self._waiting:
                                    if trustBeliefs[self._team_members[0]]['rescue_together_comp'] < -0.5:
                                        self._send_message('Found ' + vic + ' in ' + self._door['room_name'] + '. However, since you have shown your competence is non-existend ({}). I will rescue '.format(
                                            trustBeliefs[self._team_members[0]]['rescue_together_comp']) + vic + ' myself. \n \n', 'RescueBot', True)
                                    elif trustBeliefs[self._team_members[0]]['rescue_together_will'] < -0.5:
                                        self._send_message('Found ' + vic + ' in ' + self._door['room_name'] + '. However, since you have shown your willingness is non-existend ({}). I will rescue '.format(
                                            trustBeliefs[self._team_members[0]]['rescue_together_will']) + vic + ' myself. \n \n', 'RescueBot', True)
                                
                                    # If competence is high enough
                                    else:
                                        self._send_message('Found ' + vic + ' in ' + self._door['room_name'] + '. Please decide whether to "Rescue together", "Rescue alone", or "Continue" searching. \n \n \
                                            Important features to consider are: \n safe - victims rescued: ' + str(
                                            self._collected_victims) + '\n explore - areas searched: area ' + str(
                                            self._searched_rooms).replace('area ', '') + '\n \
                                            clock - extra time when rescuing alone: 15 seconds \n afstand - distance between us: ' + self._distance_human,
                                                        'RescueBot')
                                        self._waiting = True

                                if 'critical' in vic and self._answered == False and not self._waiting:
                                    self._send_message('Found ' + vic + ' in ' + self._door['room_name'] + '. Please decide whether to "Rescue" or "Continue" searching. \n\n \
                                        Important features to consider are: \n explore - areas searched: area ' + str(
                                        self._searched_rooms).replace('area',
                                                                      '') + ' \n safe - victims rescued: ' + str(
                                        self._collected_victims) + '\n \
                                        afstand - distance between us: ' + self._distance_human, 'RescueBot')
                                    self._waiting = True
                                    # Execute move actions to explore the area
                    return action, {}

                # Communicate that the agent did not find the target victim in the area while the human previously communicated the victim was located here
                if self._goal_vic in self._found_victims and self._goal_vic not in self._room_vics and \
                        self._found_victim_logs[self._goal_vic]['room'] == self._door['room_name']:
                    self._send_message(self._goal_vic + ' not present in ' + str(self._door[
                                                                                    'room_name']) + ' because I searched the whole area without finding ' + self._goal_vic + '.',
                                      'RescueBot')
                    # TASK: HUMAN INFO FALSE - DECREASE WILLINGNESS
                    self._changeTrust(by=-0.1, belief='victim_loc_will', trustBeliefs=trustBeliefs)
                    self._changeTrust(by=-0.1, belief='victim_loc_comp', trustBeliefs=trustBeliefs)
                    # Remove the victim location from memory
                    self._found_victim_logs.pop(self._goal_vic, None)
                    self._found_victims.remove(self._goal_vic)
                    self._room_vics = []
                    # Old Bug fix, keep here as comment just in case. Clear received messages (bug fix)
                    # self.received_messages = []
                    # self.received_messages_content = []
                # Add the area to the list of searched areas
                if self._door['room_name'] not in self._searched_rooms:
                    self._searched_rooms.append(self._door['room_name'])
                # Make a plan to rescue a found critically injured victim if the human decides so
                if self.received_messages_content and self.received_messages_content[
                    -1] == 'Rescue' and 'critical' in self._recent_vic:
                    # TASK: RESCUE TOGETHER CRITICIAL - INCREASE WILLINGNESS AND COMPETENCE
                    self._changeTrust(by=0.1, belief='rescue_together_comp', trustBeliefs=trustBeliefs)
                    self._changeTrust(by=0.1, belief='rescue_together_will', trustBeliefs=trustBeliefs)
                    self._rescue = 'together'
                    self._answered = True
                    self._waiting = False
                    # Tell the human to come over and help carry the critically injured victim
                    if not state[{'is_human_agent': True}]:
                        self._send_message('Please come to ' + str(self._door['room_name']) + ' to carry ' + str(
                            self._recent_vic) + ' together.', 'RescueBot')
                    # Tell the human to carry the critically injured victim together
                    if state[{'is_human_agent': True}]:
                        self._send_message('Lets carry ' + str(
                            self._recent_vic) + ' together! Please wait until I moved on top of ' + str(
                            self._recent_vic) + '.', 'RescueBot')
                    self._goal_vic = self._recent_vic
                    self._recent_vic = None
                    self._phase = Phase.PLAN_PATH_TO_VICTIM
                # Make a plan to rescue a found mildly injured victim together if the human decides so
                if self.received_messages_content and self.received_messages_content[
                    -1] == 'Rescue together' and 'mild' in self._recent_vic:
                    # TASK: RESCUE TOGETHER MILD - INCREASE WILLINGNESS
                    self._changeTrust(by=0.1, belief='rescue_together_will', trustBeliefs=trustBeliefs)
                    self._rescue = 'together'
                    self._answered = True
                    self._waiting = False
                    # Tell the human to come over and help carry the mildly injured victim
                    if not state[{'is_human_agent': True}]:
                        self._send_message('Please come to ' + str(self._door['room_name']) + ' to carry ' + str(
                            self._recent_vic) + ' together.', 'RescueBot')
                    # Tell the human to carry the mildly injured victim together
                    if state[{'is_human_agent': True}]:
                        self._send_message('Lets carry ' + str(
                            self._recent_vic) + ' together! Please wait until I moved on top of ' + str(
                            self._recent_vic) + '.', 'RescueBot')
                    self._goal_vic = self._recent_vic
                    self._recent_vic = None
                    self._phase = Phase.PLAN_PATH_TO_VICTIM
                # Make a plan to rescue the mildly injured victim alone if the human decides so, and communicate this to the human
                if self.received_messages_content and self.received_messages_content[
                    -1] == 'Rescue alone' and 'mild' in self._recent_vic:
                    self._send_message('Picking up ' + self._recent_vic + ' in ' + self._door['room_name'] + '.',
                                      'RescueBot')
                    # TASK: AGENT RESCUE ALONE MILD - DECREASE WILLINGNESS (?)
                    self._changeTrust(by=-0.1, belief='rescue_together_will', trustBeliefs=trustBeliefs)
                    self._rescue = 'alone'
                    self._answered = True
                    self._waiting = False
                    self._goal_vic = self._recent_vic
                    self._goal_loc = self._remaining[self._goal_vic]
                    self._recent_vic = None
                    self._phase = Phase.PLAN_PATH_TO_VICTIM
                # Continue searching other areas if the human decides so
                if self.received_messages_content and self.received_messages_content[-1] == 'Continue':
                    # Note: should we decrease competence (or willingness) if human chooses not to rescue victim
                    self._answered = True
                    self._waiting = False
                    self._todo.append(self._recent_vic)
                    self._recent_vic = None
                    self._phase = Phase.FIND_NEXT_GOAL
                # Remain idle untill the human communicates to the agent what to do with the found victim
                if self.received_messages_content and self._waiting and self.received_messages_content[
                    -1] != 'Rescue' and self.received_messages_content[-1] != 'Continue':
                    return None, {}
                # Find the next area to search when the agent is not waiting for an answer from the human or occupied with rescuing a victim
                if not self._waiting and not self._rescue:
                    self._recent_vic = None
                    self._phase = Phase.FIND_NEXT_GOAL
                return Idle.__name__, {'duration_in_ticks': 25}

            if Phase.PLAN_PATH_TO_VICTIM == self._phase:
                # Plan the path to a found victim using its location
                self._navigator.reset_full()
                self._navigator.add_waypoints([self._found_victim_logs[self._goal_vic]['location']])
                # Follow the path to the found victim
                self._phase = Phase.FOLLOW_PATH_TO_VICTIM

            if Phase.FOLLOW_PATH_TO_VICTIM == self._phase:
                # Start searching for other victims if the human already rescued the target victim
                if self._goal_vic and self._goal_vic in self._collected_victims:
                    self._phase = Phase.FIND_NEXT_GOAL

                # Move towards the location of the found victim
                else:
                    self._state_tracker.update(state)

                    action = self._navigator.get_move_action(self._state_tracker)
                    # If there is a valid action, return it; otherwise, switch to taking the victim
                    if action is not None:
                        return action, {}
                    self._phase = Phase.TAKE_VICTIM

            if Phase.TAKE_VICTIM == self._phase:
                # Store all area tiles in a list
                room_tiles = [info['location'] for info in state.values()
                             if 'class_inheritance' in info
                             and 'AreaTile' in info['class_inheritance']
                             and 'room_name' in info
                             and info['room_name'] == self._found_victim_logs[self._goal_vic]['room']]
                self._roomtiles = room_tiles
                objects = []
                # When the victim has to be carried by human and agent together, check whether human has arrived at the victim's location
                for info in state.values():
                    # When the victim has to be carried by human and agent together, check whether human has arrived at the victim's location
                    if (
                        # First two conditions: Checks if info is a CollectableBlock (a victim), either critical or mild & needs to be rescued together, and is inside the room.
                        ('class_inheritance' in info and 'CollectableBlock' in info['class_inheritance'] and 
                        'critical' in info['obj_id'] and info['location'] in self._roomtiles) 
                        or
                        ('class_inheritance' in info and 'CollectableBlock' in info['class_inheritance'] and 
                        'mild' in info['obj_id'] and info['location'] in self._roomtiles and self._rescue == 'together') 
                        or
                        # Last two conditions: Checks if the goal victim was already found & added to the to-do list, no more searching is needed, and the victim is either critical or mild.
                        (self._goal_vic in self._found_victims and self._goal_vic in self._todo and len(self._searched_rooms) == 0 and 
                        'class_inheritance' in info and 'CollectableBlock' in info['class_inheritance'] and 'critical' in info['obj_id'] and 
                        info['location'] in self._roomtiles) 
                        or
                        (self._goal_vic in self._found_victims and self._goal_vic in self._todo and len(self._searched_rooms) == 0 and 
                        'class_inheritance' in info and 'CollectableBlock' in info['class_inheritance'] and 'mild' in info['obj_id'] and 
                        info['location'] in self._roomtiles)
                    ):
                        
                        objects.append(info)

                        # If critical, do original flow
                        if 'critical' in self._goal_vic: 
                            self._waiting = True
                            self._moving = False
                            return None, {}

                        # You only arive here if the patient is mildly injured 
                        # If human not in sight                        
                        if not state [{'is_human_agent': True}]:
                            # Find time to wait based on willingness
                            will = trustBeliefs[self._team_members[0]]['rescue_together_will']
                            if will < 0:
                                seconds = 10
                            elif will < 0.5:
                                seconds = 15 if self._distance_human == 'close' else 20
                            else:
                                seconds = 20 if self._distance_human == 'close' else 25

                            # Only first time 
                            if self._waiting_since == None:
                                # Calculate time to wait based on risk and willingness
                                self._waiting_since = datetime.datetime.now()
                                self._send_message("Ill be waiting for {} seconds, and not a nanosecond more.".format(seconds), 'RescueBot', True)
                                self._waiting = True
                                self._moving = False

                            # When time has passed
                            if datetime.datetime.now() > self._waiting_since + datetime.timedelta(seconds = seconds):
                                self._send_message("Fine, I'll do it myself.", 'RescueBot', True)
                                self._rescue = 'alone'

                                self._waiting_since = None
                                self._waiting = False
                                self._moving = True
                            
                            # When time has not yet passed
                            else: 
                                return None, {}
                        
                        elif state [{'is_human_agent': True}]:
                            self._send_message("Ah, there you are! Come help me carry.", 'RescueBot')
                                
                        return None, {}

                # Add the victim to the list of rescued victims when it has been picked up
                if len(objects) == 0 and 'critical' in self._goal_vic or len(
                        objects) == 0 and 'mild' in self._goal_vic and self._rescue == 'together':
                    # Note: here I don't update values due to avoid updating twice,
                    # should the values be updated here instead?
                    # Note: competence should be updated here, willingness could be in either
                    self._waiting_since = None

                    self._waiting = False
                    if self._goal_vic not in self._collected_victims:
                        self._collected_victims.append(self._goal_vic)
                    self._carrying_together = True
                    # Determine the next victim to rescue or search
                    self._phase = Phase.FIND_NEXT_GOAL
                # When rescuing mildly injured victims alone, pick the victim up and plan the path to the drop zone
                if 'mild' in self._goal_vic and self._rescue == 'alone':
                    self._waiting_since = None

                    self._phase = Phase.PLAN_PATH_TO_DROPPOINT
                    if self._goal_vic not in self._collected_victims:
                        self._collected_victims.append(self._goal_vic)
                    self._carrying = True
                    return CarryObject.__name__, {'object_id': self._found_victim_logs[self._goal_vic]['obj_id'],
                                                  'human_name': self._human_name}

            if Phase.PLAN_PATH_TO_DROPPOINT == self._phase:
                self._navigator.reset_full()
                # Plan the path to the drop zone
                self._goal_loc = self._remaining[self._goal_vic]
                self._navigator.add_waypoints([self._goal_loc])
                # Follow the path to the drop zone
                self._phase = Phase.FOLLOW_PATH_TO_DROPPOINT

            if Phase.FOLLOW_PATH_TO_DROPPOINT == self._phase:
                # Communicate that the agent is transporting a mildly injured victim alone to the drop zone
                if 'mild' in self._goal_vic and self._rescue == 'alone':
                    self._send_message('Transporting ' + self._goal_vic + ' to the drop zone.', 'RescueBot')
                self._state_tracker.update(state)
                # Follow the path to the drop zone
                action = self._navigator.get_move_action(self._state_tracker)
                if action is not None:
                    return action, {}
                # Drop the victim at the drop zone
                self._phase = Phase.DROP_VICTIM

            if Phase.DROP_VICTIM == self._phase:
                # Communicate that the agent delivered a mildly injured victim alone to the drop zone
                if 'mild' in self._goal_vic and self._rescue == 'alone':
                    self._send_message('Delivered ' + self._goal_vic + ' at the drop zone.', 'RescueBot')
                # Identify the next target victim to rescue
                self._phase = Phase.FIND_NEXT_GOAL
                self._rescue = None
                self._current_door = None
                self._tick = state['World']['nr_ticks']
                self._carrying = False
                # Drop the victim on the correct location on the drop zone
                return Drop.__name__, {'human_name': self._human_name}

    def _get_drop_zones(self, state):
        '''
        @return list of drop zones (their full dict), in order (the first one is the
        place that requires the first drop)
        '''
        places = state[{'is_goal_block': True}]
        places.sort(key=lambda info: info['location'][1])
        zones = []
        for place in places:
            if place['drop_zone_nr'] == 0:
                zones.append(place)
        return zones

    def _process_messages(self, state, teamMembers, condition, trustBeliefs):
        '''
        process incoming messages received from the team members
        '''
        receivedMessages = {}
        # Create a dictionary with a list of received messages from each team member
        for member in teamMembers:
            receivedMessages[member] = []
        for mssg in self.received_messages:
            for member in teamMembers:
                if mssg.from_id == member:
                    receivedMessages[member].append(mssg.content)
        # Check the content of the received messages
        for mssgs in receivedMessages.values():
            for msg in mssgs:
                if msg in self._processed_messages:
                    continue
                self._processed_messages.append(msg)
                # If a received message involves team members searching areas, add these areas to the memory of areas that have been explored
                if msg.startswith("Search:"):
                    area = 'area ' + msg.split()[-1]
                    if area not in self._searched_rooms and trustBeliefs[teamMembers[0]]['search_room_comp'] >= 0 and trustBeliefs[teamMembers[0]]['search_room_will'] >= 0:
                        self._searched_rooms.append(area)
                        self._send_message(random.choice(search_room_good_messages), 'RescueBot', True)
                    elif trustBeliefs[teamMembers[0]]['search_room_comp'] < 0:
                        self._send_message(random.choice(search_room_competence_messages).format(
                                trustBeliefs[teamMembers[0]]['search_room_comp']), 'RescueBot', True)
                    elif trustBeliefs[teamMembers[0]]['search_room_will'] < 0:
                        self._send_message(random.choice(search_room_willingness_messages).format(trustBeliefs[teamMembers[0]]['search_room_will']), 'RescueBot', True)


                # If a received message involves team members finding victims, add these victims and their locations to memory
                if msg.startswith("Found:"):
                    if trustBeliefs[teamMembers[0]]['victim_loc_comp'] >= 0 and trustBeliefs[teamMembers[0]]['victim_loc_will'] >= 0:
                        # Identify which victim and area it concerns
                        self._send_message(random.choice(victim_loc_good_messages), 'RescueBot', True)
                        if len(msg.split()) == 6:
                            foundVic = ' '.join(msg.split()[1:4])
                        else:
                            foundVic = ' '.join(msg.split()[1:5])
                        loc = 'area ' + msg.split()[-1]
                        # Add the area to the memory of searched areas
                        if loc not in self._searched_rooms:
                            self._searched_rooms.append(loc)
                        # Add the victim and its location to memory
                        if foundVic not in self._found_victims:
                            self._found_victims.append(foundVic)
                            self._found_victim_logs[foundVic] = {'room': loc}
                        if foundVic in self._found_victims and self._found_victim_logs[foundVic]['room'] != loc:
                            self._found_victim_logs[foundVic] = {'room': loc}
                        # Decide to help the human carry a found victim when the human's condition is 'weak'
                        if condition == 'weak':
                            self._rescue = 'together'
                        # Add the found victim to the to do list when the human's condition is not 'weak'
                        if 'mild' in foundVic and condition != 'weak':
                            self._todo.append(foundVic)

                    elif trustBeliefs[teamMembers[0]]['victim_loc_comp'] < 0:
                        self._send_message(random.choice(victim_loc_competence_messages).format(trustBeliefs[teamMembers[0]]['victim_loc_comp']), 'RescueBot', True)
                    elif trustBeliefs[teamMembers[0]]['victim_loc_will'] < 0:
                        self._send_message(random.choice(victim_loc_willingness_messages).format(trustBeliefs[teamMembers[0]]['victim_loc_will'] ), 'RescueBot', True)
                # If a received message involves team members rescuing victims, add these victims and their locations to memory
                if msg.startswith('Collect:'):
                    # Identify which victim and area it concerns
                    if len(msg.split()) == 6:
                        collectVic = ' '.join(msg.split()[1:4])
                    else:
                        collectVic = ' '.join(msg.split()[1:5])
                    loc = 'area ' + msg.split()[-1]
                    # Add the area to the memory of searched areas
                    if loc not in self._searched_rooms:
                        self._searched_rooms.append(loc)
                    # Add the victim and location to the memory of found victims
                    if collectVic not in self._found_victims:
                        self._found_victims.append(collectVic)
                        self._found_victim_logs[collectVic] = {'room': loc}
                    if collectVic in self._found_victims and self._found_victim_logs[collectVic]['room'] != loc:
                        self._found_victim_logs[collectVic] = {'room': loc}
                    # Add the victim to the memory of rescued victims when the human's condition is not weak
                    if condition != 'weak' and collectVic not in self._collected_victims:
                        self._collected_victims.append(collectVic)
                    # Decide to help the human carry the victim together when the human's condition is weak
                    if condition == 'weak':
                        self._rescue = 'together'
                # If a received message involves team members asking for help with removing obstacles, add their location to memory and come over
                if msg.startswith('Remove:'):
                    # Come over immediately when the agent is not carrying a victim
                    if not self._carrying:
                        # Identify at which location the human needs help
                        area = 'area ' + msg.split()[-1]
                        self._door = state.get_room_doors(area)[0]
                        self._doormat = state.get_room(area)[-1]['doormat']
                        if area in self._searched_rooms:
                            self._searched_rooms.remove(area)
                        # Old Bug fix, keep here as comment just in case. Clear received messages (bug fix)
                        # self.received_messages = []
                        # self.received_messages_content = []
                        self._moving = True
                        self._remove = True
                        if self._waiting and self._recent_vic:
                            self._todo.append(self._recent_vic)
                        self._waiting = False
                        # Let the human know that the agent is coming over to help
                        self._send_message(
                            'Moving to ' + str(self._door['room_name']) + ' to help you remove an obstacle.',
                            'RescueBot')
                        # Plan the path to the relevant area
                        self._phase = Phase.PLAN_PATH_TO_ROOM
                    # Come over to help after dropping a victim that is currently being carried by the agent
                    else:
                        area = 'area ' + msg.split()[-1]
                        self._send_message('Will come to ' + area + ' after dropping ' + self._goal_vic + '.',
                                          'RescueBot')
            # Store the current location of the human in memory
            if mssgs and mssgs[-1].split()[-1] in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13',
                                                   '14']:
                self._human_loc = int(mssgs[-1].split()[-1])

    def _loadBelief(self, members, folder):
        '''
        Loads trust belief values if agent already collaborated with human before, otherwise trust belief values are initialized using default values.
        '''
        # Create a dictionary with trust values for all team members
        trustBeliefs = {}
        # Set a default starting trust value
        trustfile_header = []
        trustfile_contents = []
        # Check if agent already collaborated with this human before, if yes: load the corresponding trust values, if no: initialize using default trust values
        with open(folder + '/beliefs/currentTrustBelief.csv') as csvfile:
            reader = csv.reader(csvfile, delimiter=';', quotechar="'")
            # Initialize default trust values
            trustBeliefs[self._human_name] = {
                'search_room_comp': 0.2,
                'search_room_will': 0.2,
                'obstacle_removal_comp': 0.0,
                'obstacle_removal_will': 0.0,
                'victim_loc_comp': 0.1,
                'victim_loc_will': 0.1,
                'rescue_together_comp': 0.3,
                'rescue_together_will': 0.1
            }
            for row in reader:
                if trustfile_header == []:
                    trustfile_header = row
                    continue
                # Retrieve trust values
                if row and row[0] == self._human_name:
                    name = row[0]
                    search_room_comp = float(row[1])
                    search_room_will = float(row[2])
                    obstacle_removal_comp = float(row[3])
                    obstacle_removal_will = float(row[4])
                    victim_loc_comp = float(row[5])
                    victim_loc_will = float(row[6])
                    rescue_together_comp = float(row[7])
                    rescue_together_will = float(row[8])
                    trustBeliefs[name] = {
                        'search_room_comp': search_room_comp,
                        'search_room_will': search_room_will,
                        'obstacle_removal_comp': obstacle_removal_comp,
                        'obstacle_removal_will': obstacle_removal_will,
                        'victim_loc_comp': victim_loc_comp,
                        'victim_loc_will': victim_loc_will,
                        'rescue_together_comp': rescue_together_comp,
                        'rescue_together_will': rescue_together_will
                    }
                    return trustBeliefs

        with open(folder + '/beliefs/allTrustBeliefs.csv') as csvfile:
            reader = csv.reader(csvfile, delimiter=';', quotechar="'")
            # Initialize default trust values
            for row in reader:
                if trustfile_header == []:
                    trustfile_header = row
                    continue
                # Retrieve trust values 
                if row and row[0] == self._human_name:
                    name = row[0]
                    search_room_comp = float(row[1])
                    search_room_will = float(row[2])
                    obstacle_removal_comp = float(row[3])
                    obstacle_removal_will = float(row[4])
                    victim_loc_comp = float(row[5])
                    victim_loc_will = float(row[6])
                    rescue_together_comp = float(row[7])
                    rescue_together_will = float(row[8])
                    trustBeliefs[name] = {
                        'search_room_comp': search_room_comp,
                        'search_room_will': search_room_will,
                        'obstacle_removal_comp': obstacle_removal_comp,
                        'obstacle_removal_will': obstacle_removal_will,
                        'victim_loc_comp': victim_loc_comp,
                        'victim_loc_will': victim_loc_will,
                        'rescue_together_comp': rescue_together_comp,
                        'rescue_together_will': rescue_together_will
                    }
                    return trustBeliefs

        return trustBeliefs

    def _changeTrust(self, by: float, belief: str, trustBeliefs):
        valid_beliefs = {
            "name", "search_room_comp", "search_room_will", "obstacle_removal_comp",
            "obstacle_removal_will", "victim_loc_comp", "victim_loc_will",
            "rescue_together_comp", "rescue_together_will"
        }

        if belief not in valid_beliefs:
            raise ValueError(f"Invalid belief: {belief}. Must be one of {valid_beliefs}")

        trustBeliefs[self._human_name][belief] = np.clip(trustBeliefs[self._human_name][belief] + by, -1, 1)
        return self._trustBelief(self._team_members, trustBeliefs, self._folder, self.received_messages)

    def _trustBelief(self, members, trustBeliefs, folder, receivedMessages):
        '''
        Baseline implementation of a trust belief. Creates a dictionary with trust belief scores for each team member, for example based on the received messages.
        '''
        # Update the trust value based on for example the received messages
        # for message in receivedMessages:
        #     # Increase agent trust in a team member that rescued a victim
        #     if 'Collect' in message:
        #         trustBeliefs[self._human_name]['competence'] += 0.10
        #         # Restrict the competence belief to a range of -1 to 1
        #         trustBeliefs[self._human_name]['competence'] = np.clip(trustBeliefs[self._human_name]['competence'], -1,
        #                                                                1)
        # Save current trust belief values so we can later use and retrieve them to add to a csv file with all the logged trust belief values
        with open(folder + '/beliefs/currentTrustBelief.csv', mode='w') as csv_file:
            csv_writer = csv.writer(csv_file, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            csv_writer.writerow(['name',
                                 'search_room_comp', 'search_room_will',
                                 'obstacle_removal_comp', 'obstacle_removal_will',
                                 'victim_loc_comp', 'victim_loc_will',
                                 'rescue_together_comp', 'rescue_together_will'])
            csv_writer.writerow([self._human_name,
                                 trustBeliefs[self._human_name]['search_room_comp'],
                                 trustBeliefs[self._human_name]['search_room_will'],
                                 trustBeliefs[self._human_name]['obstacle_removal_comp'],
                                 trustBeliefs[self._human_name]['obstacle_removal_will'],
                                 trustBeliefs[self._human_name]['victim_loc_comp'],
                                 trustBeliefs[self._human_name]['victim_loc_will'],
                                 trustBeliefs[self._human_name]['rescue_together_comp'],
                                 trustBeliefs[self._human_name]['rescue_together_will']
                                 ])

        return trustBeliefs


    # Yeah, we worked around your workaround. You're welcome
    def _send_message(self, mssg, sender, force = False):
        '''
        send messages from agent to other team members
        '''
        msg = Message(content=mssg, from_id=sender)
        if force or msg.content not in self.received_messages_content and 'Our score is' not in msg.content:
            self.send_message(msg)
            self._send_messages.append(msg.content)
        # Sending the hidden score message (DO NOT REMOVE)
        if 'Our score is' in msg.content:
            self.send_message(msg)

    def _getClosestRoom(self, state, objs, currentDoor):
        '''
        calculate which area is closest to the agent's location
        '''
        agent_location = state[self.agent_id]['location']
        locs = {}
        for obj in objs:
            locs[obj] = state.get_room_doors(obj)[0]['location']
        dists = {}
        for room, loc in locs.items():
            if currentDoor != None:
                dists[room] = utils.get_distance(currentDoor, loc)
            if currentDoor == None:
                dists[room] = utils.get_distance(agent_location, loc)

        return min(dists, key=dists.get)

    def _efficientSearch(self, tiles):
        '''
        efficiently transverse areas instead of moving over every single area tile
        '''
        x = []
        y = []
        for i in tiles:
            if i[0] not in x:
                x.append(i[0])
            if i[1] not in y:
                y.append(i[1])
        locs = []
        for i in range(len(x)):
            if i % 2 == 0:
                locs.append((x[i], min(y)))
            else:
                locs.append((x[i], max(y)))
        return locs
