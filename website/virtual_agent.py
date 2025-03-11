import multiprocessing
import time
import json

from home_connector import get_quantity_per_type

import py_trees
from py_trees.composites import Sequence, Selector, Parallel
from numpy import random
import requests

utterance_label_to_topic = {
    'DontKnowDifferenceBetweenTwoStrengthLevels' : 'strength',
    'DontKnowStrengthLevelDefinition' : 'strength',
    'DontKnowStrengthLevels': 'strength',
    'NoDiagnosis': 'strength',

    'DontKnowMeaningOfQuantValue' : 'quantity',
    'DontKnowQuantRange': 'quantity',
    'NoDiagnosis': 'quantity',

    'DontKnowDifferenceBetweenTwoTempLevels' : 'temp',
    'DontKnowTempLevelDefinition' : 'temp',
    'DontKnowTempLevels' : 'temp',
    'NoDiagnosis' : 'temp',

    'DontKnowName' : 'type',
    'DontKnowTypes': 'type',
    'DontKnowIfTypeIsAvailable': 'type',
    'NoDiagnosis': 'type'
}

class Listen(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection):
        """Configure the name of the behaviour."""

        super(Listen, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member
        self.message_agenda = []

        self.blackboard = self.attach_blackboard_client(name="The bot's interpretation of the user's last utterance",
                                                        namespace="user_utterance")
        self.blackboard.register_key(key="message", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="communicative_intent", access=py_trees.common.Access.WRITE)

        self.blackboard.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="strength", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="temp", access=py_trees.common.Access.WRITE)

        self.task_state = self.attach_blackboard_client(name="State of the coffee production task",
                                                        namespace="task_state")
        self.task_state.register_key(key="type", access=py_trees.common.Access.READ)
        self.task_state.register_key(key="strength", access=py_trees.common.Access.READ)
        self.task_state.register_key(key="quantity", access=py_trees.common.Access.READ)
        self.task_state.register_key(key="temp", access=py_trees.common.Access.READ)

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)
        self.count = 0

    def update(self) -> py_trees.common.Status:
        message_arrived = False

        while self.team_member.poll():
            message = self.team_member.recv()
            label = json.loads(message)
            print("bot gets message from user: %s" % message)
            self.message_agenda.append(label)

        if len(self.message_agenda) > 0:
            message_arrived = True

            self.blackboard.wandke_choose_strength = 'undefined'
            self.blackboard.wandke_choose_quantity = 'undefined'
            self.blackboard.wandke_choose_type = 'undefined'
            self.blackboard.wandke_choose_temp = 'undefined'

            label = self.message_agenda[0]
            self.message_agenda.pop(0)

            for activity, wandke_level in label.items():
                self.blackboard.set(activity, wandke_level, True)

        if message_arrived:
            new_status = py_trees.common.Status.SUCCESS
        else:
            new_status = py_trees.common.Status.RUNNING

        return new_status

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)

class ProcessType(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection):
        """Configure the name of the behaviour."""

        super(ProcessType, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member

        self.blackboard = self.attach_blackboard_client(name="The bot's interpretation of the user's last utterance",
                                                        namespace="user_utterance")
        self.blackboard.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)

        self.blackboard.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="strength", access=py_trees.common.Access.WRITE)

        self.own_belief = self.attach_blackboard_client(name="The bot's belief state",
                                                        namespace="bot_belief")
        self.own_belief.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="information_need", access=py_trees.common.Access.WRITE)

        self.task_state = self.attach_blackboard_client(name="State of the coffee production task",
                                                        namespace="task_state")
        self.task_state.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="strength", access=py_trees.common.Access.WRITE)

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def update(self) -> py_trees.common.Status:
        if self.blackboard.wandke_choose_type == 'NoDiagnosis':
            if self.own_belief.wandke_choose_type == 'undefined' or self.own_belief.wandke_choose_type == 'NoDiagnosis' or self.own_belief.wandke_choose_type == 'in focus':
                print(f"bot updates self.task_state.type. Current value {self.task_state.type}")
                if self.task_state.type == 'default':
                    self.task_state.type = self.blackboard.type
                    self.own_belief.wandke_choose_type = 'NoDiagnosis'
                    if self.own_belief.information_need == 'type':
                        self.own_belief.information_need = 'undefined'
                else:
                    # Nutzer hat anscheinend die Kaffeesorte geändert.

                    self.own_belief.wandke_choose_type = 'TypeValueConflict'
            # else:
                # in einem früheren Interaktionsschritt hatte der Bot Probleme
                # mit dem Task oder dem Nutzerinput.
                # ist der neue input eine Lösung für die Probleme?

                # einfach überschreiben; das ist nicht fertig!

            self.blackboard.wandke_choose_type = 'undefined'
            new_status = py_trees.common.Status.SUCCESS
        elif self.blackboard.wandke_choose_type != 'undefined':
            self.own_belief.wandke_choose_type = self.blackboard.wandke_choose_type

            # jetzt muss eine geeignete Reaktion festgelet werden.
            # sie hängt von dem Problem ab, das der Nutzer kommuniziert hat.
            new_status = py_trees.common.Status.SUCCESS
        else:
            new_status = py_trees.common.Status.FAILURE

            # type is not focussed in the belief state assumed for the user

        return new_status

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)


class ProcessTemp(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection):
        """Configure the name of the behaviour."""

        super(ProcessTemp, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member

        self.blackboard = self.attach_blackboard_client(name="The bot's interpretation of the user's last utterance",
                                                        namespace="user_utterance")
        self.blackboard.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)

        self.blackboard.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="strength", access=py_trees.common.Access.WRITE)

        self.own_belief = self.attach_blackboard_client(name="The bot's belief state",
                                                        namespace="bot_belief")
        self.own_belief.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="information_need", access=py_trees.common.Access.WRITE)

        self.task_state = self.attach_blackboard_client(name="State of the coffee production task",
                                                        namespace="task_state")
        self.task_state.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="strength", access=py_trees.common.Access.WRITE)

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def update(self) -> py_trees.common.Status:
        if self.blackboard.wandke_choose_temp == 'NoDiagnosis':
            if self.own_belief.wandke_choose_temp == 'undefined' or self.own_belief.wandke_choose_temp == 'NoDiagnosis'or self.own_belief.wandke_choose_temp == 'in focus':
                print(f"bot updates self.task_state.temp. Current value {self.task_state.temp}")
                if self.task_state.temp == 'default':
                    self.task_state.temp = self.blackboard.temp
                    self.own_belief.wandke_choose_temp = 'NoDiagnosis'
                    if self.own_belief.information_need == 'temp':
                        self.own_belief.information_need = 'undefined'
                else:
                    # Nutzer hat anscheinend die Kaffeesorte geändert.

                    self.own_belief.wandke_choose_temp = 'TempValueConflict'
            # else:
            # in einem früheren Interaktionsschritt hatte der Bot Probleme
            # mit dem Task oder dem Nutzerinput.
            # ist der neue input eine Lösung für die Probleme?

            # einfach überschreiben; das ist nicht fertig!

            new_status = py_trees.common.Status.SUCCESS
        elif self.blackboard.wandke_choose_temp != 'undefined':
            self.own_belief.wandke_choose_temp = self.blackboard.wandke_choose_temp

            # jetzt muss eine geeignete Reaktion festgelet werden.
            # sie hängt von dem Problem ab, das der Nutzer kommuniziert hat.
            new_status = py_trees.common.Status.SUCCESS
        else:
            new_status = py_trees.common.Status.FAILURE

            # type is not focussed in the belief state assumed for the user

        return new_status

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)


class ProcessStrength(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection):
        """Configure the name of the behaviour."""

        super(ProcessStrength, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member

        self.blackboard = self.attach_blackboard_client(name="The bot's interpretation of the user's last utterance",
                                                        namespace="user_utterance")
        self.blackboard.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)

        self.blackboard.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="strength", access=py_trees.common.Access.WRITE)

        self.own_belief = self.attach_blackboard_client(name="The bot's belief state",
                                                        namespace="bot_belief")
        self.own_belief.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="information_need", access=py_trees.common.Access.WRITE)

        self.task_state = self.attach_blackboard_client(name="State of the coffee production task",
                                                        namespace="task_state")
        self.task_state.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="strength", access=py_trees.common.Access.WRITE)

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def update(self) -> py_trees.common.Status:
        if self.blackboard.wandke_choose_strength == 'NoDiagnosis':
            if self.own_belief.wandke_choose_strength == 'undefined' or self.own_belief.wandke_choose_strength == 'NoDiagnosis'or self.own_belief.wandke_choose_strength == 'in focus':
                print(f"bot updates self.task_state.strength. Current value {self.task_state.strength}")
                if self.task_state.strength == 'default':
                    self.task_state.strength = self.blackboard.strength
                    self.own_belief.wandke_choose_strength = 'NoDiagnosis'
                    if self.own_belief.information_need == 'strength':
                        self.own_belief.information_need = 'undefined'
                else:
                    # Nutzer hat anscheinend die Kaffeesorte geändert.

                    self.own_belief.wandke_choose_strength = 'StrengthValueConflict'
            # else:
            # in einem früheren Interaktionsschritt hatte der Bot Probleme
            # mit dem Task oder dem Nutzerinput.
            # ist der neue input eine Lösung für die Probleme?

            # einfach überschreiben; das ist nicht fertig!

            new_status = py_trees.common.Status.SUCCESS
        elif self.blackboard.wandke_choose_strength != 'undefined':
            self.own_belief.wandke_choose_strength = self.blackboard.wandke_choose_strength

            # jetzt muss eine geeignete Reaktion festgelet werden.
            # sie hängt von dem Problem ab, das der Nutzer kommuniziert hat.
            new_status = py_trees.common.Status.SUCCESS
        else:
            new_status = py_trees.common.Status.FAILURE

            # type is not focussed in the belief state assumed for the user

        return new_status

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)


class ProcessQuantity(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection):
        """Configure the name of the behaviour."""

        super(ProcessQuantity, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member

        self.blackboard = self.attach_blackboard_client(name="The bot's interpretation of the user's last utterance",
                                                        namespace="user_utterance")
        self.blackboard.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)

        self.blackboard.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="strength", access=py_trees.common.Access.WRITE)

        self.own_belief = self.attach_blackboard_client(name="The bot's belief state",
                                                        namespace="bot_belief")
        self.own_belief.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="information_need", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="content_to_communicate", access=py_trees.common.Access.WRITE)

        self.own_belief.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="strength", access=py_trees.common.Access.WRITE)

        self.task_state = self.attach_blackboard_client(name="State of the coffee production task",
                                                        namespace="task_state")
        self.task_state.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="strength", access=py_trees.common.Access.WRITE)

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def update(self) -> py_trees.common.Status:
        if self.blackboard.wandke_choose_quantity == 'NoDiagnosis':
            if self.own_belief.wandke_choose_quantity == 'undefined' or self.own_belief.wandke_choose_quantity == 'NoDiagnosis' or self.own_belief.wandke_choose_quantity == 'in focus':
                print(f"bot updates self.task_state.quantity. Current value {self.task_state.quantity}")
                if self.task_state.quantity == 'default':
                    if self.task_state.type != 'default':
                        min_quantity, max_quantity = get_quantity_per_type(self.task_state.type)

                        user_quantity = int(self.blackboard.quantity)
                        if user_quantity < min_quantity:
                            self.own_belief.wandke_choose_quantity = 'UserRequestedValueTooLowForType'
                            self.own_belief.content_to_communicate = f"Die gewählte Kaffeesorte ist {self.task_state.type}. Dafür ist die gewünschte Menge zu wenig. Es müssen mindestens {min_quantity} ml gewählt werden."
                        elif user_quantity > max_quantity:
                            self.own_belief.wandke_choose_quantity = 'UserRequestedValueTooHighForType'
                            self.own_belief.content_to_communicate = f"Die gewählte Kaffeesorte ist {self.task_state.type}. Dafür ist die gewünschte Menge zu hoch. Es dürfen höchstens {max_quantity} ml gewählt werden."
                        else:
                            self.own_belief.wandke_choose_quantity = 'NoDiagnosis'
                            self.own_belief.quantity = user_quantity
                            self.task_state.quantity = user_quantity

                            self.own_belief.information_need = 'undefined'
                    else:
                        # im task state steht noch keine Sorte.
                        # damit kann nicht geprüft werden, ob die Menge sinnvoll ist.

                        self.own_belief.wandke_choose_quantity = 'TypeNotYetSpecified'
                        self.own_belief.content_to_communicate = f"Die Kaffeesorte ist noch nicht ausgewählt. Bevor sie nicht gewählt ist, kann die Menge nicht angegeben werden."

                    if self.own_belief.information_need == 'quantity':
                        self.own_belief.information_need = 'undefined'
                else:
                    # Nutzer hat anscheinend die Kaffeesorte geändert.

                    self.own_belief.wandke_choose_quantity = 'QuantityValueConflict'
                    self.own_belief.content_to_communicate = f"Für die Menge ist schon {self.task_state.quantity} ausgewählt werden. Weil jetzt auch {self.blackboard.quantity} gewählt wurde, kann bei der Kaffeemaschine die Menge nicht eingestellt werden."

                print(f"update results in this assumption: {self.own_belief.wandke_choose_quantity}")
            # else:
            # in einem früheren Interaktionsschritt hatte der Bot Probleme
            # mit dem Task oder dem Nutzerinput.
            # ist der neue input eine Lösung für die Probleme?

            new_status = py_trees.common.Status.SUCCESS
        elif self.blackboard.wandke_choose_quantity != 'undefined':
            self.own_belief.wandke_choose_quantity = self.blackboard.wandke_choose_quantity

            # jetzt muss eine geeignete Reaktion festgelet werden.
            # sie hängt von dem Problem ab, das der Nutzer kommuniziert hat.
            new_status = py_trees.common.Status.SUCCESS
        else:
            new_status = py_trees.common.Status.FAILURE

            # type is not focussed in the belief state assumed for the user

        return new_status

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)


class RequestConfirmation(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection):
        """Configure the name of the behaviour."""

        super(RequestConfirmation, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member

        self.own_belief = self.attach_blackboard_client(name="The bot's belief state",
                                                        namespace="bot_belief")
        self.own_belief.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="information_need", access=py_trees.common.Access.WRITE)

        self.task_state = self.attach_blackboard_client(name="State of the coffee production task",
                                                        namespace="task_state")
        self.task_state.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="strength", access=py_trees.common.Access.WRITE)

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def update(self) -> py_trees.common.Status:
        if self.own_belief.wandke_production_state == 'in focus':
            self.own_belief.wandke_production_state = 'complete'
            new_status = py_trees.common.Status.SUCCESS
        elif self.own_belief.wandke_production_state == 'complete':
            new_status = py_trees.common.Status.SUCCESS
        else:
            new_status = py_trees.common.Status.FAILURE

        return new_status

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)


class StartCoffeeMaker(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection, agenda):
        """Configure the name of the behaviour."""

        super(StartCoffeeMaker, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member
        self.agenda = agenda

        self.user_says = self.attach_blackboard_client(name="The bot's interpretation of the user's last utterance",
                                                        namespace="user_utterance")
        self.user_says.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)

        self.own_belief = self.attach_blackboard_client(name="The bot's belief state",
                                                        namespace="bot_belief")
        self.own_belief.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.own_belief.register_key(key="information_need", access=py_trees.common.Access.WRITE)

        self.task_state = self.attach_blackboard_client(name="State of the coffee production task",
                                                        namespace="task_state")
        self.task_state.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="strength", access=py_trees.common.Access.WRITE)

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def update(self) -> py_trees.common.Status:
        if self.user_says.wandke_production_state == 'started' and self.own_belief.wandke_production_state == 'complete':
            self.own_belief.wandke_production_state = 'ready'
            self.own_belief.information_need = 'undefined'

            json_data = {'action' : 'set_coffee_settings',
                         'type': self.task_state.type,
                         'strength': self.task_state.strength,
                         'quantity': self.task_state.quantity,
                         'temp': self.task_state.temp}
            self.agenda.append(json.dumps(json_data))

            self.agenda.append(f"{{\"communicative_intent\" : \"inform\", \"wandke_production_state\" : \"ready\"}}")

            new_status = py_trees.common.Status.SUCCESS
        else:
            new_status = py_trees.common.Status.FAILURE

        return new_status

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)


class Planning(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection, agenda):
        """Configure the name of the behaviour."""

        super(Planning, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member
        self.agenda = agenda

        self.task_state = py_trees.blackboard.Client(name="State of the coffee production task",
                                                     namespace="task_state")
        self.bot_believes = py_trees.blackboard.Client(name="The bot's belief state",
                                                       namespace="bot_belief")
        self.user_says = self.attach_blackboard_client(name="The bot's interpretation of the user's last utterance",
                                                        namespace="user_utterance")

        self.bot_believes.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="information_need", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="communication_established", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="message_pending", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="strength", access=py_trees.common.Access.WRITE)
        self.bot_believes.register_key(key="quantity", access=py_trees.common.Access.WRITE)

        self.task_state.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="temp", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="strength", access=py_trees.common.Access.WRITE)
        self.task_state.register_key(key="quantity", access=py_trees.common.Access.WRITE)

        self.user_says.register_key("wandke_production_state", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="type", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="strength", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="quantity", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="temperature", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="wandke_production_state", access=py_trees.common.Access.WRITE)
        self.user_says.register_key(key="communicative_intent", access=py_trees.common.Access.WRITE)

        self.team_member = team_member

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def information_sufficient(self):
        if self.task_state.type != 'default' and self.task_state.temp != 'default' and self.task_state.quantity != 'default' and self.task_state.strength != 'undefined':
            return True
        else:
            return False

    def update(self) -> py_trees.common.Status:
        print(f"Proactive: {self.bot_believes.information_need} - {self.bot_believes.wandke_choose_type}")
        print(f"Proactive: {self.bot_believes.information_need} - {self.bot_believes.wandke_choose_strength}")
        print(f"Proactive: {self.bot_believes.information_need} - {self.bot_believes.wandke_choose_quantity}")
        print(f"Proactive: {self.bot_believes.information_need} - {self.bot_believes.wandke_choose_temp}")
        print(f"Proactive: {self.bot_believes.information_need} - {self.bot_believes.wandke_production_state}")

        if len(self.agenda) > 0:
            return py_trees.common.Status.FAILURE

        # wird aus der neuesten Äußerung des Nutzers angenommen, dass er kommunizieren möchte,
        # bei einer Aktion nicht selbstständig handeln zu können (also auf einer Wandke-Ebene
        # ein 'Problem' zu haben?

        if self.user_says.wandke_choose_type != 'undefined' and self.bot_believes.wandke_choose_type == 'in focus':
            print(f"User hat ein Problem mit Type: {self.user_says.wandke_choose_type}")
            new_status = py_trees.common.Status.SUCCESS

        if self.user_says.wandke_choose_strength != 'undefined' and self.bot_believes.wandke_choose_strength == 'in focus':
            print(f"User hat ein Problem mit Strength: {self.user_says.wandke_choose_strength}")
            new_status = py_trees.common.Status.SUCCESS

        if self.user_says.wandke_choose_quantity != 'undefined' and self.bot_believes.wandke_choose_quantity == 'in focus':
            print(f"User hat ein Problem mit Quantity: {self.user_says.wandke_choose_quantity}")
            new_status = py_trees.common.Status.SUCCESS

        if self.user_says.wandke_choose_temp != 'undefined' and self.bot_believes.wandke_choose_temp == 'in focus':
            print(f"User hat ein Problem mit Temperature: {self.user_says.wandke_choose_temp}")
            new_status = py_trees.common.Status.SUCCESS

        # hat der bot bei der Verarbeitung der letzten Äußerung des Nutzers selbst
        # ein Problem diagnostiziert, das er jetzt kommunzieren möchte?

        if self.bot_believes.wandke_choose_type != 'undefined' and self.bot_believes.wandke_choose_type != 'in focus' and self.bot_believes.wandke_choose_type != 'NoDiagnosis':
            print(f"Bot hat ein Problem mit Type: {self.bot_believes.wandke_choose_type}")
            new_status = py_trees.common.Status.SUCCESS

        if self.bot_believes.wandke_choose_strength != 'undefined' and self.bot_believes.wandke_choose_strength != 'in focus' and self.bot_believes.wandke_choose_strength != 'NoDiagnosis':
            print(f"Bot hat ein Problem mit Strength: {self.bot_believes.wandke_choose_strength}")
            new_status = py_trees.common.Status.SUCCESS

        if self.bot_believes.wandke_choose_quantity != 'undefined' and self.bot_believes.wandke_choose_quantity != 'in focus' and self.bot_believes.wandke_choose_quantity != 'NoDiagnosis':
            print(f"Bot hat ein Problem mit Quantity: {self.bot_believes.wandke_choose_quantity}")
            if self.bot_believes.wandke_choose_quantity == 'UserRequestedValueTooLowForType':
                self.agenda.append(f"{{\"communicative_intent\" : \"inform\", \"quantity\" : \"{self.bot_believes.quantity}\", \"wandke_choose_quantity\" : \"{self.bot_believes.wandke_choose_quantity}\"}}")
            elif self.bot_believes.wandke_choose_quantity == 'UserRequestedValueTooHighForType':
                self.agenda.append(f"{{\"communicative_intent\" : \"inform\", \"quantity\" : \"{self.bot_believes.quantity}\", \"wandke_choose_quantity\" : \"{self.bot_believes.wandke_choose_quantity}\"}}")
            elif self.bot_believes.wandke_choose_quantity == 'TypeNotYetSpecified':
                self.agenda.append(f"{{\"communicative_intent\" : \"inform\", \"quantity\" : \"{self.bot_believes.quantity}\", \"wandke_choose_quantity\" : \"{self.bot_believes.wandke_choose_quantity}\"}}")
            elif self.bot_believes.wandke_choose_quantity == 'QuantityValueConflict':
                self.agenda.append(f"{{\"communicative_intent\" : \"inform\", \"quantity\" : \"{self.bot_believes.quantity}\", \"wandke_choose_quantity\" : \"{self.bot_believes.wandke_choose_quantity}\"}}")
            else:
                print("This problem is unknown.")

            self.bot_believes.information_need = 'quantity'
            self.bot_believes.wandke_choose_quantity = 'in focus'
            self.agenda.append(
                f"{{\"communicative_intent\" : \"request_information\", \"wandke_choose_quantity\" : \"in focus\"}}")

            new_status = py_trees.common.Status.SUCCESS

        if self.bot_believes.wandke_choose_temp != 'undefined' and self.bot_believes.wandke_choose_temp != 'in focus' and self.bot_believes.wandke_choose_temp != 'NoDiagnosis':
            print(f"Bot hat ein Problem mit Temperature: {self.bot_believes.wandke_choose_temp}")
            new_status = py_trees.common.Status.SUCCESS

        if self.bot_believes.information_need == 'undefined':
            # im Folgenden ist eine Strategie fest implementiert mit der der bot den user
            # nach Information über Parameter fragt

            if self.bot_believes.communication_established == 'undefined':
                be_proactive = random.choice([0,1], p=[0.0,1], size=(1))
                if be_proactive[0] == 1:
                    self.bot_believes.communication_established = 'ok'
                    self.agenda.append(f"{{\"communicative_intent\" : \"greeting\"}}")

                    new_status = py_trees.common.Status.SUCCESS
                else:
                    new_status = py_trees.common.Status.FAILURE
            elif self.bot_believes.wandke_choose_type == 'undefined':
                self.bot_believes.information_need = 'type'
                self.bot_believes.wandke_choose_type = 'in focus'

                self.agenda.append(f"{{\"communicative_intent\" : \"request_information\", \"wandke_choose_type\" : \"in focus\"}}")

                new_status = py_trees.common.Status.SUCCESS
            elif self.bot_believes.wandke_choose_strength == 'undefined':
                self.bot_believes.information_need = 'strength'
                self.bot_believes.wandke_choose_strength = 'in focus'

                self.agenda.append(f"{{\"communicative_intent\" : \"request_information\", \"wandke_choose_strength\" : \"in focus\"}}")

                new_status = py_trees.common.Status.SUCCESS
            elif self.bot_believes.wandke_choose_quantity == 'undefined':
                self.bot_believes.information_need = 'quantity'
                self.bot_believes.wandke_choose_quantity = 'in focus'

                self.agenda.append(f"{{\"communicative_intent\" : \"request_information\", \"wandke_choose_quantity\" : \"in focus\"}}")

                new_status = py_trees.common.Status.SUCCESS
            elif self.bot_believes.wandke_choose_temp == 'undefined':
                self.bot_believes.information_need = 'temp'
                self.bot_believes.wandke_choose_temp = 'in focus'

                self.agenda.append( f"{{\"communicative_intent\" : \"request_information\", \"wandke_choose_temp\" : \"in focus\"}}")

                new_status = py_trees.common.Status.SUCCESS
            elif self.bot_believes.wandke_production_state == 'undefined' and self.information_sufficient():
                self.bot_believes.information_need = 'production'
                self.bot_believes.wandke_production_state = 'in focus'

                self.agenda.append(f"{{\"communicative_intent\" : \"request_information\", \"wandke_production_state\" : \"in focus\"}}")

                new_status = py_trees.common.Status.SUCCESS
            else:
                print("do not know what to ask for")
                new_status = py_trees.common.Status.FAILURE
        else:
            print("Proactive fails.")
            new_status = py_trees.common.Status.FAILURE

  #      json_data = {'member' : 'bot',
  #                   'belief' : 'task_state',
  #                   'type' : task_state.type,
  #                   'strength' : task_state.strength,
  #                   'temp' : task_state.temp,
  #                   'quantity' : task_state.quantity}

  #      response = requests.post("http://127.0.0.1:5001/log_belief_state", data=json_data)
  #      print(f"{response.status_code} {response.headers['content-type']}")
        return new_status

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)


# Suche die Klasse Communicating in virtual_agent.py und ersetze die update-Methode:

class Communicating(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection, agenda):
        """Configure the name of the behaviour."""

        super(Communicating, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member
        self.agenda = agenda
        self.message_id = 0

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def update(self) -> py_trees.common.Status:
        if len(self.agenda) > 0:
            todo_next = self.agenda[0]
            msg = json.loads(todo_next)
            if "communicative_intent" in msg.keys():
                del self.agenda[0]

                print(f"on agenda: {todo_next}")
                self.message_id += 1

                # Hier nicht mehr per HTTP-Route Nachrichten senden, nur über die pipe
                # json_data = {'username': 'assistant', 'id': self.message_id, 'message': todo_next}
                # response = requests.post("http://127.0.0.1:5001/message", data=json_data)
                # print(response)

                msg['id'] = self.message_id
                self.team_member.send(json.dumps(msg))

                return py_trees.common.Status.SUCCESS
            else:
                return py_trees.common.Status.FAILURE
        else:
            return py_trees.common.Status.FAILURE

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)

class Acting(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, team_member: multiprocessing.connection, agenda):
        """Configure the name of the behaviour."""

        super(Acting, self).__init__(name)
        self.logger.debug("%s.__init__()" % self.__class__.__name__)
        self.team_member = team_member
        self.agenda = agenda
        self.action_id = 0

    def setup(self, **kwargs: int) -> None:
        self.logger.debug("setup: %s" % self.__class__.__name__)

    def initialise(self) -> None:
        self.logger.debug("initialise: %s" % self.__class__.__name__)
        self.logger.debug("status: %s" % self.status)

    def update(self) -> py_trees.common.Status:
        print(f"ACTING update {len(self.agenda)}")
        if len(self.agenda) > 0:
            todo_next = self.agenda[0]
            msg = json.loads(todo_next)
            if "action" in msg.keys():
                del self.agenda[0]

                if msg["action"] == "set_coffee_settings":
                    del msg["action"]

                    response = requests.post("http://127.0.0.1:5001/coffee_settings", data=msg)
                    print(f"ACTING obtains response: {response}")

                self.action_id += 1

                return py_trees.common.Status.SUCCESS
            else:
                return py_trees.common.Status.FAILURE
        else:
            return py_trees.common.Status.FAILURE

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self.logger.debug("terminate: %s" % self.__class__.__name__)


def create_root(team_member: multiprocessing.connection.Connection, agenda)-> py_trees.behaviour.Behaviour:
    root = Selector("Act or React",
                    True,
                    [Selector("ProactiveBehaviour",
                              True,
                              children=[Communicating("Bot talks", team_member, agenda),
                                        Planning("Bot plans", team_member, agenda),
                                        Acting("Bot acts", team_member, agenda)
                                        ]),
                     Sequence("Bot Processing Pipeline",
                              True,
                              [Listen("Listen for User Input", team_member),
                               Selector("Process User Input",
                                        True,
                                        children=[ProcessTemp("Temperature", team_member),
                                                  ProcessType("Type", team_member),
                                                  ProcessQuantity("Quantity", team_member),
                                                  ProcessStrength("Strength", team_member),
                                                  RequestConfirmation("Confirm Parameters", team_member)]),
                               StartCoffeeMaker("Start Coffee Machine", team_member, agenda)])])
    return root

def create_chatbot(pipe_connection: multiprocessing.connection.Connection) -> None:
    agenda = []

    user_says_that = py_trees.blackboard.Client(name="The bot's interpretation of the user's last utterance",
                                                namespace="user_utterance")
    user_says_that.register_key(key="type", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="strength", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="quantity", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="temperature", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="wandke_production_state", access=py_trees.common.Access.WRITE)
    user_says_that.register_key(key="communicative_intent", access=py_trees.common.Access.WRITE)

    user_says_that.type = 'default'
    user_says_that.strength = 'default'
    user_says_that.temperature = 'default'
    user_says_that.quantity = 'default'
    user_says_that.wandke_choose_type = 'undefined'
    user_says_that.wandke_choose_temp = 'undefined'
    user_says_that.wandke_choose_quantity = 'undefined'
    user_says_that.wandke_choose_strength= 'undefined'
    user_says_that.wandke_production_state = 'undefined'
    user_says_that.communicative_intent = 'undefined'

    user_belief = py_trees.blackboard.Client(name="The user's belief state",
                                             namespace="user_belief")
    user_belief.register_key(key="type", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="strength", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="quantity", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="temperature", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="wandke_production_state", access=py_trees.common.Access.WRITE)
    user_belief.register_key(key="communicative_intent", access=py_trees.common.Access.WRITE)

    user_belief.type = 'default'
    user_belief.strength = 'default'
    user_belief.temperature = 'default'
    user_belief.quantity = 'default'
    user_belief.wandke_choose_type = 'undefined'
    user_belief.wandke_choose_temp = 'undefined'
    user_belief.wandke_choose_quantity = 'undefined'
    user_belief.wandke_choose_strength= 'undefined'
    user_belief.wandke_production_state = 'undefined'

    bot_believes = py_trees.blackboard.Client(name="The bot's belief state",
                                              namespace="bot_belief")
    bot_believes.register_key(key="type", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="strength", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="quantity", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="temperature", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="wandke_choose_type", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="wandke_choose_temp", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="wandke_choose_quantity", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="wandke_choose_strength", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="wandke_production_state", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="information_need", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="content_to_communicate", access=py_trees.common.Access.WRITE)
    bot_believes.register_key(key="communication_established", access=py_trees.common.Access.WRITE)

    bot_believes.type = 'default'
    bot_believes.strength = 'default'
    bot_believes.temperature = 'default'
    bot_believes.quantity = 'default'
    bot_believes.wandke_choose_type = 'undefined'
    bot_believes.wandke_choose_temp = 'undefined'
    bot_believes.wandke_choose_quantity = 'undefined'
    bot_believes.wandke_choose_strength = 'undefined'
    bot_believes.wandke_production_state = 'undefined'
    bot_believes.information_need = 'undefined'
    bot_believes.content_to_communicate = 'undefined'
    bot_believes.communication_established = 'undefined'

    task_state = py_trees.blackboard.Client(name="State of the coffee production task",
                                            namespace="task_state")
    task_state.register_key(key="type", access=py_trees.common.Access.WRITE)
    task_state.register_key(key="strength", access=py_trees.common.Access.WRITE)
    task_state.register_key(key="quantity", access=py_trees.common.Access.WRITE)
    task_state.register_key(key="temp", access=py_trees.common.Access.WRITE)

    task_state.type = 'default'
    task_state.strength = 'default'
    task_state.temp = 'default'
    task_state.quantity = 'default'

    root = create_root(pipe_connection, agenda)
 #   py_trees.display.render_dot_tree(root)

    while True:
        root.tick_once()
        time.sleep(0.25)
