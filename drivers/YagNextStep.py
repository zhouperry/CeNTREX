import logging
import numpy as np
from copy import copy
import time

def split(string, separator=","):
    return [x.strip() for x in string.split(separator)]


class YagNextStep:
    def __init__(self, parent, time_offset):
        self.parent = parent
        self.time_offset = time_offset
        self.yagisolator = self.parent.devices["YagIsolator"]
        self.zaber = self.parent.devices["ZaberTMM"]
        self.pxie = self.parent.devices["PXIe5171"]

        self.param1 = "ch1"
        self.paramnorm = "ch2"

        self.absorption_cutoff = 0.95
        self.max_retries = 10
        self.abs_min = 1
        self.nr_trial_shots = 4

        self.timestamp_last_fetched = 0

        self.verification_string = "YagNextStep"
        self.timestamp_last_fetched = 0

        self.warnings = []
        self.new_attributes = []

        # shape and type of the array of returned data
        self.shape = (4, )
        self.dtype = float

    def __enter__(self):
        return self
    def __exit__(self, *exc):
        pass

    #################################################
    # Helper Functions
    #################################################

    def Strip(self, string, to_strip):
        return string.strip(to_strip)

    #################################################
    # CeNTREX DAQ Commands
    #################################################

    def GetWarnings(self):
        warnings = self.warnings
        self.warnings = []
        return warnings

    def ReadAbsTraceNorm(self):
        absorption_background = 1500
        absorption = None
        for _ in range(self.nr_trial_shots):
            self.pxie.commands.append("ReadValue()")
            abs, absorption_norm = self.FetchData()
            abs = absorption/ absorption_norm
            abs /= absorption[absorption_background: ].mean()
            if absorption is None:
                absorption = abs
            else:
                absorption += abs
        absorption /= self.nr_trial_shots
        return np.min(absorption[50:200])
    
    def ReadValue(self):
        return [time.time() - self.time_offset, self.max_retries, self.absorption_cutoff, self.abs_min]

    def NextStepWithCutoff(self):
        self.abs_min = 1
        abs_min = []
        nr_trials = 0
        while self.abs_min < self.absorption_cutoff:
            nr_trials += 1
            if nr_trials > self.max_retries:
                logging.warning(f"YagNextStep: Max retry of {nr_trials} reached before finding signal, abs_min={abs_min}")
                self.warnings.append("YagNextStep: Max retries reached before finding signal")
                return
            self.zaber.commands.append("nextStep()")
            self.yagisolator.commands.append(f"SetNrQswitchesGUI({self.nr_trial_shots})")
            self.abs_min = self.ReadAbsTraceNorm()
            abs_min.append(self.abs_min)

    def set_absorption_cutoff(self, absorption_cutoff: float):
        self.absorption_cutoff = absorption_cutoff

    #################################################
    # Device Commands
    #################################################

    def FetchData(self):
        """
        Attempting to fetch data from the specified fast and slow device.
        """
        try:
            data1_queue = list(self.parent.devices[self.pxie].config["plots_queue"])
        except KeyError:
            logging.warning(f"HistogramPlotterNorm: device {self.pxie} not found")
            return []        

        timestamps1 = np.asarray([d[-1][0]["timestamp"] for d in data1_queue])

        if self.timestamp_last_fetched == 0:
            mask = np.ones(len(data1_queue), dtype=bool)
        else:
            mask = timestamps1 > self.timestamp_last_fetched

        if (len(mask) == 0) or (mask.sum() == 0):
            return [], []

        self.timestamp_last_fetched = timestamps1[mask][-1]

        # extract the desired parameter 1 and 2
        col_names1 = split(
            self.parent.devices[self.dev1].config["attributes"]["column_names"]
        )
        
        try:
            idx1 = col_names1.index(self.param1)
            idx1norm = col_names1.index(self.paramnorm)
        except IndexError:
            logging.error("Error in HistogramPlotter: param not found: " + self.param1)
            return [], []

        data1_queue = [data1_queue[idx] for idx, m in enumerate(mask) if m]

        if self.timestamp_last_fetched == 0:
            unprocessed_data = [d[0][0][idx1] for d in data1_queue]
            unprocessed_data_norm = [d[0][0][idx1norm] for d in data1_queue]
        else:
            unprocessed_data = []
            unprocessed_data_norm = []
            for d in data1_queue:
                d = d[0]
                if d.shape[0] > 1:
                    print("hit d.shape[0] > 1")
                    for di in d:
                        unprocessed_data.append(di[0][idx1])
                        unprocessed_data_norm.append(di[0][idx1norm])
                else:
                    unprocessed_data.append(d[0][idx1])
                    unprocessed_data_norm.append(d[0][idx1norm])
        return unprocessed_data, unprocessed_data_norm

    def ProcessData(self):
        """
        Processing data from the fast device
        """
        # most time spent in FetchData()
        unprocessed_data, unprocessed_data_norm = self.FetchData()

        if self.processed_changed:
            logging.info("processing changed")
            self.x_data.clear()
            self.y_data.clear()
            self.y_data_norm.clear()
            self.x_data_new.clear()
            self.y_data_new.clear()
            self.y_data_norm_new.clear()
            self.redo_binning_flag = True
            self.processed_changed = False
            return

        if len(self.x_data) == 0:
            return

        if len(unprocessed_data) == 0:
            return
        for idx in reversed(range(len(unprocessed_data))):
            # self.processing string contains y which is then evaluated
            y = unprocessed_data[-idx - 1]  # noqa: F841
            y_norm = unprocessed_data_norm[-idx - 1]  # noqa: F841
            yi = eval(self.processing)
            yin = eval(self.processingnorm)
            self.y_data.append(yi)
            self.y_data_norm.append(yin)
            self.y_data_new.append(yi)
            self.y_data_norm_new.append(yin)
