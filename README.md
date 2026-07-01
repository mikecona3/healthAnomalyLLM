<h1>Health Data Anomaly Detection</h1>
<h2>Helping you discover health issues sooner</h2>

<p>Introducing a personalized LLM that is paired with a detection algorithm to help detect potential health conditions/issues early!
The LLM introduces "hard limits" that are considered "dangerous" across the board, while "personal limits" dynamically adjust over time on
an individual level. All of this data will be encrypted and live on device!</p>

<b>Please Note:</b>
<p>This is only the LLM model. It is non working, purposely, as it requires health data to be synced for the full model to work properly. 
The model that lives on Github is typically a few versions behind the actual "for production" model.</p>


<h3>Changelog:</h3>
  <div>
    <h6>Current Known Bugs:</h6>
      <ul>
        <li>Health data syncs correctly ~85% of the time</li>
        <li>Blood oxygen, blood gluclose levels do not produce a result</li>
        <li>Level 1 (algo) sometimes skips flags to send to level 2 resulting in missed flags</li>
        <li>Results list in app sometimes will time out and show no results</li>
      </ul>
  </div>
  
  
  <div>
    <h6>v0.5.1</h6>
    <h6>What's New?</h6>
      <ul>
        <li>Added 5 more metrics!</li>
        <li>Some metrics are now labeled 'optional' to prevent return errors</li>
        <li>Now able to sync data with Apple Health, Google Health, & some standalone devices</li>
      </ul>
  </div>
