<h1>Personalized Health Anomaly Detection LLM</h1>

<p>Introducing a brand-new algoirthm for tracking health data and a personalized LLM that helps detects health conditions/potential issues early!
The LLM includes "hard limits" that are considered dangerous and never change, "personal limits" that dynamically adjust over time based on 
the individual person, and this data all lives on device so your personal health data isn't shared.</p>

<p>* Note: This is a non-working standalone LLM, purposely. It includes no data and can not independently receive data. The model that lives here
  is typically between 0.1-0.3 versions behind what's happening in the background.</p>

<h3><b>Changelog</b></h3>
<p>v0.2 beta</p>
  <ul>
    <li>Added support for more health metrics; blood oxygen fixed, blood gluclose added</li>
    <li>Code clean-up; structure has changed as health data is displayed</li>
    <li>Health data syncing works most of the time</li>
  </ul>

<p>Known bugs</p>
  <ul>
    <li>Coming soon</li>
  </ul>


<p>v0.1 beta</p>
  <ul>
    <li>Initial commit</li>
    <li>Basic structure of LLM</li>
    <li>Health data syncing</li>
  </ul>

<p>Known bugs</p>
  <ul>
    <li>Blood oxygen, blood gluclose levels not being read (algorithmically) and will not produce data</li>
    <li>Sometimes skips level 1 flags to send to level 2 LLM</li>
    <li>Results list sometimes times-out and produces no results to user </li>
  </ul>
