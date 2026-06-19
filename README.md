# Personalized Health Anomaly Detection LLM 

Introducing a brand-new algoirthm for tracking health data and a personalized LLM that helps detects health conditions/potential issues early!
The LLM includes "hard limits" that are considered dangerous and never change, "personal limits" that dynamically adjust over time based on 
the individual person, and this data all lives on device so your personal health data isn't shared. 

* Note: This is a non-working standalone LLM, purposely. It includes no data and can not independently receive data. The model that lives here
  is typically between 0.1-0.3 versions behind what's happening in the background.

# Changelog

v0.1 beta 
  Comments:
    -Initial commit 
    -Basic structure of LLM

  Known bugs:
    -Blood oxygen, blood gluclose levels not being read (algorithmically) and will not produce data 
    -Sometimes skips level 1 flags to send to level 2 LLM 
    -Results list sometimes times-out and produces no results to user 
